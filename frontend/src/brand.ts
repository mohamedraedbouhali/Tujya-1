/**
 * The name visitors see. It is the one written in the logo (src/assets/logo.png, cut from
 * photo.png at the project root), so change both together.
 */
export const APP_NAME = "Tujya";

/** Shown on every page that talks about medicines, word for word (decision D53). */
export const DISCLAIMER = "Information uniquement, consultez un pharmacien ou un médecin.";

/**
 * The public data Tujya is built on, shown on the start page and in every footer. Names and
 * licences stay as published; what each source gives is translated (intro.sourceGives, same
 * order). The first three addresses match backend/app/pharma_loader.py.
 */
export const SOURCES: { name: string; licence: string | null; url: string }[] = [
  { name: "NLM C3PI", licence: "ODbL", url: "https://data.lhncbc.nlm.nih.gov/public/Pills/" },
  { name: "RxNav / RxNorm", licence: null, url: "https://lhncbc.nlm.nih.gov/RxNav/APIs/" }, // NLM terms
  { name: "DDInter 2.0", licence: "CC BY-NC-SA 4.0", url: "https://ddinter2.scbdd.com/" },
  { name: "openFDA labels", licence: "CC0", url: "https://open.fda.gov/" },
  { name: "PubMed", licence: null, url: "https://pubmed.ncbi.nlm.nih.gov/" }, // NLM terms
];

/** What the data build of October 2026 contains (docs/VISION.md, INTERACTIONS.md, RAG.md). */
export const FACTS = {
  pills: 150,
  ingredients: 82,
  interactions: 40508,
  passages: 8661,
} as const;
