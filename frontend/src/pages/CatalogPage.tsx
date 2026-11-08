import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type CellLine, type Drug, type Page } from "../api";
import {
  Alert,
  Badge,
  formatNumber,
  Pagination,
  staggerIndex,
  TableSkeleton,
} from "../components";
import { useDebounced, useQuery } from "../hooks";
import { useT, type Messages } from "../i18n";
import { Icon, type IconName } from "../icons";

const PAGE_SIZE = 25;

interface Column<T> {
  id: string;
  header: string;
  cell: (row: T) => ReactNode;
  numeric?: boolean;
}

interface CatalogProps<T> {
  title: string;
  subtitle: string;
  icon: IconName;
  searchPlaceholder: string;
  load: (query: { q: string; page: number; page_size: number }, signal: AbortSignal) => Promise<Page<T>>;
  rowKey: (row: T) => string;
  columns: Column<T>[];
}

/** A searchable, paginated table over one of the processed tables. */
function Catalog<T>({ title, subtitle, icon, searchPlaceholder, load, rowKey, columns }: CatalogProps<T>) {
  // The search lives in the address (?q=...), so a search can be linked to and survives reload.
  const t = useT();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [page, setPage] = useState(1);
  const q = useDebounced(search.trim());
  const result = useQuery((signal) => load({ q, page, page_size: PAGE_SIZE }, signal), [q, page]);

  useEffect(() => {
    if ((params.get("q") ?? "") !== q) setParams(q ? { q } : {}, { replace: true });
  }, [q, params, setParams]);

  return (
    <>
      <header className="page-header">
        <div className="page-title">
          <span className="page-icon">
            <Icon name={icon} size={24} />
          </span>
          <div>
            <h1>{title}</h1>
            <p className="muted">{subtitle}</p>
          </div>
        </div>
        {result.data && (
          <span className="result-count" aria-live="polite">
            <strong>{formatNumber(result.data.total)}</strong> {q ? t.catalog.matching : t.catalog.inTotal}
          </span>
        )}
      </header>

      <div className="toolbar">
        <label className="search-box">
          <Icon name="search" />
          <input
            type="search"
            aria-label={searchPlaceholder}
            placeholder={searchPlaceholder}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
          />
        </label>
      </div>

      {result.error && <Alert>{result.error}</Alert>}
      {!result.data && result.loading && <TableSkeleton rows={10} />}

      {result.data && (
        <div className="card table-card" aria-busy={result.loading}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  {columns.map((column) => (
                    <th key={column.id} className={column.numeric ? "num" : undefined}>
                      {column.header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {/* Rows are keyed by record, so the ones a new page brings in play their entrance. */}
                {result.data.items.map((row, index) => (
                  <tr key={rowKey(row)} className="row-enter" style={staggerIndex(index)}>
                    {columns.map((column) => (
                      <td key={column.id} className={column.numeric ? "num" : undefined}>
                        {column.cell(row)}
                      </td>
                    ))}
                  </tr>
                ))}
                {result.data.items.length === 0 && (
                  <tr>
                    <td colSpan={columns.length} className="empty">
                      {q ? t.catalog.nothingMatches(q) : t.catalog.empty}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pagination
            page={page}
            pageSize={PAGE_SIZE}
            total={result.data.total}
            onPage={setPage}
          />
        </div>
      )}
    </>
  );
}

const dash = <span className="muted">—</span>;

function Sources({ names }: { names: string[] }) {
  return (
    <span className="badge-row">
      {names.map((name) => (
        <Badge tone="neutral" key={name}>
          {name}
        </Badge>
      ))}
    </span>
  );
}

function External({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

const drugColumns = (t: Messages): Column<Drug>[] => [
  {
    id: "drug",
    header: t.catalog.drug,
    cell: (drug) => (
      <>
        <span className="cell-title">{drug.name}</span>
        {drug.synonyms.length > 0 && (
          <span className="cell-sub">{drug.synonyms.slice(0, 3).join(" · ")}</span>
        )}
      </>
    ),
  },
  {
    id: "pubchem",
    header: "PubChem",
    cell: (drug) =>
      drug.pubchem_cid == null ? (
        dash
      ) : (
        <External href={`https://pubchem.ncbi.nlm.nih.gov/compound/${drug.pubchem_cid}`}>
          {drug.pubchem_cid}
        </External>
      ),
  },
  {
    id: "chembl",
    header: "ChEMBL",
    cell: (drug) =>
      drug.chembl_id ? (
        <External
          href={`https://www.ebi.ac.uk/chembl/explore/compound/${encodeURIComponent(drug.chembl_id)}`}
        >
          {drug.chembl_id}
        </External>
      ) : (
        dash
      ),
  },
  { id: "sources", header: t.catalog.sources, cell: (drug) => <Sources names={drug.sources} /> },
  {
    id: "measurements",
    header: t.catalog.measurements,
    numeric: true,
    cell: (drug) => formatNumber(drug.n_measurements),
  },
];

const cellLineColumns = (t: Messages): Column<CellLine>[] => [
  {
    id: "cell-line",
    header: t.catalog.cellLine,
    cell: (line) => <span className="cell-title">{line.name}</span>,
  },
  { id: "tissue", header: t.catalog.tissue, cell: (line) => line.tissue ?? dash },
  { id: "disease", header: t.catalog.disease, cell: (line) => line.disease ?? dash },
  {
    id: "depmap",
    header: t.catalog.depmap,
    cell: (line) =>
      line.depmap_id ? (
        <External href={`https://depmap.org/portal/cell_line/${encodeURIComponent(line.depmap_id)}`}>
          {line.depmap_id}
        </External>
      ) : (
        dash
      ),
  },
  { id: "sources", header: t.catalog.sources, cell: (line) => <Sources names={line.sources} /> },
  {
    id: "measurements",
    header: t.catalog.measurements,
    numeric: true,
    cell: (line) => formatNumber(line.n_measurements),
  },
];

export function DrugsPage() {
  const t = useT();
  return (
    <Catalog
      title={t.catalog.drugsTitle}
      subtitle={t.catalog.drugsSubtitle}
      icon="pill"
      searchPlaceholder={t.catalog.drugsSearch}
      load={api.drugs}
      rowKey={(drug) => drug.drug_id}
      columns={drugColumns(t)}
    />
  );
}

export function CellLinesPage() {
  const t = useT();
  return (
    <Catalog
      title={t.catalog.cellLinesTitle}
      subtitle={t.catalog.cellLinesSubtitle}
      icon="cells"
      searchPlaceholder={t.catalog.cellLinesSearch}
      load={api.cellLines}
      rowKey={(line) => line.cell_line_id}
      columns={cellLineColumns(t)}
    />
  );
}
