import { useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { api, errorMessage, type ProfileChanges, type User } from "../api";
import { useAuth } from "../auth";
import {
  Alert,
  Avatar,
  Badge,
  formatDate,
  PasswordStrength,
  SubmitButton,
  TextField,
} from "../components";
import { useT } from "../i18n";
import { Icon } from "../icons";
import { signatureFromFile, squarePhoto } from "../imageTools";
import { SignaturePad } from "../SignaturePad";

const MIN_PASSWORD_LENGTH = 8;
const IMAGE_TYPES = "image/jpeg,image/png,image/webp";

type Notice = { kind: "success" | "error"; text: string } | null;

/** Spaces collapsed, as the server stores it, so "unchanged" is detected correctly. */
function tidyPhone(phone: string): string {
  return phone.split(/\s+/).filter(Boolean).join(" ");
}

/** Run one profile request: busy flag, then a notice with the result. */
function useProfileAction() {
  const { setUser } = useAuth();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);

  const run = async (action: () => Promise<User>, success: string): Promise<boolean> => {
    setBusy(true);
    setNotice(null);
    try {
      setUser(await action());
      setNotice({ kind: "success", text: success });
      return true;
    } catch (failure) {
      setNotice({ kind: "error", text: errorMessage(failure) });
      return false;
    } finally {
      setBusy(false);
    }
  };

  return { busy, notice, run };
}

function ProfileHeader({ user }: { user: User }) {
  const t = useT();
  const { busy, notice, run } = useProfileAction();
  const fileRef = useRef<HTMLInputElement>(null);

  const choose = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = ""; // the same file can be picked again later
    if (file) {
      void run(async () => api.uploadPhoto(await squarePhoto(file)), t.profile.photoUpdated);
    }
  };

  return (
    <header className="profile-header">
      <div className="profile-photo">
        <Avatar name={user.full_name} src={user.photo_url} size="lg" />
        <button
          type="button"
          className="profile-photo-edit"
          aria-label={user.photo_url ? t.profile.changePhoto : t.profile.addPhoto}
          title={user.photo_url ? t.profile.changePhoto : t.profile.addPhoto}
          onClick={() => fileRef.current?.click()}
          disabled={busy}
        >
          <Icon name="camera" size={16} />
        </button>
        {busy && (
          <span className="profile-photo-busy" role="status" aria-label={t.profile.savingPhoto}>
            <span className="btn-spinner" />
          </span>
        )}
        <input ref={fileRef} type="file" accept={IMAGE_TYPES} onChange={choose} hidden />
      </div>
      <div className="profile-summary">
        <h1>{user.full_name}</h1>
        <p className="profile-contact muted">
          <span>{user.email}</span>
          {user.phone && <span>{user.phone}</span>}
        </p>
        <p className="profile-meta">
          <Badge tone={user.role}>{t.roles[user.role]}</Badge>
          <span className="muted">{t.profile.memberSince(formatDate(user.created_at))}</span>
          <span className="muted">{t.profile.lastSignIn(formatDate(user.last_login_at, true))}</span>
        </p>
        <div className="profile-photo-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
          >
            <Icon name="upload" size={16} />
            {user.photo_url ? t.profile.changePhoto : t.profile.uploadPhoto}
          </button>
          {user.photo_url && (
            <button
              type="button"
              className="btn btn-ghost btn-sm btn-ghost-danger"
              onClick={() => void run(api.deletePhoto, t.profile.photoRemoved)}
              disabled={busy}
            >
              <Icon name="trash" size={16} />
              {t.common.remove}
            </button>
          )}
        </div>
        {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      </div>
    </header>
  );
}

function DetailsForm({ user }: { user: User }) {
  const t = useT();
  const { busy, notice, run } = useProfileAction();
  const [fullName, setFullName] = useState(user.full_name);
  const [email, setEmail] = useState(user.email);
  const [phone, setPhone] = useState(user.phone ?? "");
  const [password, setPassword] = useState("");

  const emailChanged = email.trim().toLowerCase() !== user.email;
  const changed =
    fullName.trim() !== user.full_name || emailChanged || tidyPhone(phone) !== (user.phone ?? "");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const changes: ProfileChanges = { full_name: fullName, phone: tidyPhone(phone) };
    if (emailChanged) {
      changes.email = email.trim();
      changes.current_password = password;
    }
    const saved = await run(() => api.updateProfile(changes), t.profile.detailsSaved);
    if (saved) {
      setPassword("");
      setEmail((value) => value.trim().toLowerCase());
      setPhone((value) => tidyPhone(value));
      setFullName((value) => value.trim());
    }
  };

  return (
    <form className="card form" onSubmit={submit}>
      <h2>{t.profile.detailsTitle}</h2>
      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      <TextField
        label={t.common.fullName}
        value={fullName}
        onChange={setFullName}
        autoComplete="name"
        maxLength={120}
        required
      />
      <TextField
        label={t.common.email}
        type="email"
        value={email}
        onChange={setEmail}
        autoComplete="email"
        maxLength={254}
        required
      />
      {emailChanged && (
        <TextField
          label={t.common.currentPassword}
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
          maxLength={128}
          hint={t.profile.emailPasswordHint}
          required
        />
      )}
      <TextField
        label={t.profile.phone}
        type="tel"
        value={phone}
        onChange={setPhone}
        autoComplete="tel"
        inputMode="tel"
        maxLength={32}
        placeholder="+216 20 123 456"
        hint={t.profile.phoneHint}
      />
      <div className="form-actions">
        <SubmitButton busy={busy} disabled={!changed}>
          {t.common.saveChanges}
        </SubmitButton>
      </div>
    </form>
  );
}

function SignatureCard({ user }: { user: User }) {
  const t = useT();
  const { busy, notice, run } = useProfileAction();
  const [drawing, setDrawing] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const save = async (image: Blob) => {
    if (await run(() => api.uploadSignature(image), t.profile.signatureSaved)) {
      setDrawing(false);
    }
  };

  const choose = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) {
      void run(
        async () => api.uploadSignature(await signatureFromFile(file)),
        t.profile.signatureSaved,
      );
    }
  };

  return (
    <section className="card signature-card">
      <div>
        <h2>{t.profile.signatureTitle}</h2>
        <p className="muted">{t.profile.signatureHint}</p>
      </div>
      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}

      {drawing ? (
        <SignaturePad busy={busy} onSave={save} onCancel={() => setDrawing(false)} />
      ) : (
        <>
          {user.signature_url ? (
            <div className="signature-paper">
              <img src={user.signature_url} alt={t.profile.signatureAlt(user.full_name)} />
            </div>
          ) : (
            <div className="signature-empty">
              <Icon name="pen" size={22} />
              <span>{t.profile.noSignature}</span>
            </div>
          )}
          <div className="signature-actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setDrawing(true)}
              disabled={busy}
            >
              <Icon name="pen" size={16} />
              {user.signature_url ? t.profile.drawNew : t.profile.draw}
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => fileRef.current?.click()}
              disabled={busy}
            >
              <Icon name="upload" size={16} />
              {t.profile.uploadImage}
            </button>
            {user.signature_url && (
              <button
                type="button"
                className="btn btn-ghost btn-sm btn-ghost-danger"
                onClick={() => void run(api.deleteSignature, t.profile.signatureRemoved)}
                disabled={busy}
              >
                <Icon name="trash" size={16} />
                {t.common.remove}
              </button>
            )}
            <input ref={fileRef} type="file" accept={IMAGE_TYPES} onChange={choose} hidden />
          </div>
        </>
      )}
    </section>
  );
}

function PasswordForm() {
  const t = useT();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (next !== confirm) {
      setNotice({ kind: "error", text: t.profile.newMismatch });
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setNotice({ kind: "success", text: t.profile.passwordChanged });
    } catch (failure) {
      setNotice({ kind: "error", text: errorMessage(failure) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card form" onSubmit={submit}>
      <h2>{t.profile.passwordTitle}</h2>
      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      <TextField
        label={t.common.currentPassword}
        type="password"
        value={current}
        onChange={setCurrent}
        autoComplete="current-password"
        maxLength={128}
        required
      />
      <TextField
        label={t.common.newPassword}
        type="password"
        value={next}
        onChange={setNext}
        autoComplete="new-password"
        minLength={MIN_PASSWORD_LENGTH}
        maxLength={128}
        hint={t.profile.atLeast(MIN_PASSWORD_LENGTH)}
        required
      />
      <PasswordStrength password={next} minLength={MIN_PASSWORD_LENGTH} />
      <TextField
        label={t.profile.confirmNew}
        type="password"
        value={confirm}
        onChange={setConfirm}
        autoComplete="new-password"
        maxLength={128}
        required
      />
      <div className="form-actions">
        <SubmitButton busy={busy}>{t.profile.passwordTitle}</SubmitButton>
      </div>
    </form>
  );
}

export default function Profile() {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <>
      <ProfileHeader user={user} />
      <div className="two-columns">
        <DetailsForm user={user} />
        <PasswordForm />
      </div>
      <SignatureCard user={user} />
    </>
  );
}
