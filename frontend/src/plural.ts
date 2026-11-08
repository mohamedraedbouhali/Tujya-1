/**
 * Pick the right plural form for a count, by the language's own rules (Intl.PluralRules):
 * English and French have "one" and "other"; Russian also has "few" (2-4) and "many" (5-20).
 * A "#" in the chosen form is replaced by the count, formatted for that language.
 */
export interface PluralForms {
  one?: string;
  few?: string;
  many?: string;
  other: string;
}

const rules = new Map<string, Intl.PluralRules>();
const numbers = new Map<string, Intl.NumberFormat>();

export function plural(locale: string, count: number, forms: PluralForms): string {
  let rule = rules.get(locale);
  if (!rule) {
    rule = new Intl.PluralRules(locale);
    rules.set(locale, rule);
  }
  let number = numbers.get(locale);
  if (!number) {
    number = new Intl.NumberFormat(locale);
    numbers.set(locale, number);
  }
  const form = forms[rule.select(count) as keyof PluralForms] ?? forms.other;
  return form.replaceAll("#", number.format(count));
}
