/** Definitions written for a reader who knows the law and not this tool.
 *  Roles and types are the skill's vocabulary; the counts cited are this corpus. */
export type Entry = { title: string; body: string };

export const GLOSSARY: Record<string, Entry> = {
  // --- rule roles, in the order they run ---
  role: {
    title: "Role",
    body:
      "Where a rule sits in the staged pattern: orientation, then extraction, then validation, " +
      "reconciliation, and human review. Earlier stages establish what the row is so later ones " +
      "can rely on it.",
  },
  orientation: {
    title: "Orientation",
    body:
      "Establishes what the row is and which documents it was built from, before anything " +
      "substantive is read. Runs first so later rules can route on its answer.",
  },
  extraction: {
    title: "Extraction",
    body: "Pulls a substantive fact out of the documents. The bulk of most modules.",
  },
  validation: {
    title: "Validation",
    body:
      "Checks a fact, or supplies the key another rule or table joins on, so an answer can be " +
      "tested rather than taken on trust.",
  },
  reconciliation: {
    title: "Reconciliation",
    body: "Compares an answer against another source to confirm the two agree.",
  },
  human_review: {
    title: "Human review",
    body: "Flags the row for an attorney to decide rather than answering it.",
  },

  // --- Harvey column types ---
  native_type: {
    title: "Type",
    body:
      "The Harvey column type, which decides the shape of the answer. Classify returns one of a " +
      "configured set; the typed columns return a value; Free Response returns prose.",
  },
  Classify: {
    title: "Classify",
    body:
      "Returns exactly one value from a configured option set, so the column can be filtered and " +
      "counted. An answer outside the set is a defect.",
  },
  FreeResponse: {
    title: "Free Response",
    body: "Returns prose. Not constrained to a value set, so it cannot be filtered reliably.",
  },
  Verbatim: { title: "Verbatim", body: "Returns an exact quote copied from the document." },
  Date: { title: "Date", body: "A typed date value. Its silence state is `Not stated`." },
  Number: { title: "Number", body: "A typed numeric value. Its silence state is `Not stated`." },
  Currency: { title: "Currency", body: "A typed money value. Its silence state is `Not stated`." },
  Duration: { title: "Duration", body: "A typed length of time. Its silence state is `Not stated`." },

  // --- lifecycle ---
  status: {
    title: "Status",
    body:
      "Where a rule is in its life: draft (written, not tested), testing (being evaluated), " +
      "verified (passed its test set), retired (no longer in use).",
  },
  draft: { title: "Draft", body: "Written but not yet tested against documents." },
  testing: { title: "Testing", body: "Being evaluated against a test set." },
  verified: { title: "Verified", body: "Ran against its test set with no open failures." },
  retired: { title: "Retired", body: "No longer in use. Kept for the record." },

  // --- staleness ---
  staleness: {
    title: "Staleness",
    body:
      "Whether a rule's last recorded result still reflects the rule as it stands now. Never run " +
      "means no result exists at all.",
  },
  never_run: { title: "Never run", body: "No result has ever been recorded for this rule." },
  current: { title: "Current", body: "Nothing has changed since the last recorded run." },
  stale_direct: {
    title: "Stale",
    body: "The rule's own text changed after the last run, so the recorded result is out of date.",
  },
  stale_transitive: {
    title: "Stale via upstream",
    body:
      "The rule itself did not change, but something it depends on did, so its answer may no " +
      "longer hold.",
  },
  open_failures: {
    title: "Open failures",
    body:
      "Recorded results that failed and have not since passed on a rerun. Nothing to show until " +
      "a run has been recorded.",
  },

  // --- graph ---
  reference_graph: {
    title: "Reference graph",
    body:
      "Every `@Column` reference one prompt makes to another inside this module. Upstream sits " +
      "left, what reads it sits right. Change something on the left and everything to its right " +
      "needs re-checking.",
  },
  degree: {
    title: "Reference count",
    body: "How many rules this one connects to. Shown only above three, so hubs stand out.",
  },
  review_unit: {
    title: "Review unit",
    body:
      "What one row of the table represents. Everything a rule says is scoped to that unit and " +
      "nothing outside it.",
  },
  not_referenced: {
    title: "Not referenced",
    body:
      "Rules no other rule in this module reads and which read nothing themselves. Often correct, " +
      "sometimes a sign a reference was written and never used.",
  },

  // --- consistency ---
  divergent_rules: {
    title: "Same name, different rules",
    body:
      "One column name used in several modules with different types, options, or silence states. " +
      "A reviewer can get two different answers to the same question depending which module ran.",
  },
  distinct_option_sets: {
    title: "Different option sets",
    body:
      "How many genuinely different value sets are in use under this one name. Two modules sharing " +
      "a name and a set is agreement; this counts the disagreement.",
  },
  agreed_by_all: {
    title: "Agreed by all",
    body: "Options every module using this name offers. Everything else is unique to some of them.",
  },
  name_variant: {
    title: "Similar names, no shared concept",
    body:
      "Names close enough to be the same idea, with no shared concept tag to confirm it. Found by " +
      "token overlap, so read it as a prompt to check, not a verdict.",
  },

  // --- finding codes seen in the UI ---
  DEAD_REFERENCE: {
    title: "Dead reference",
    body:
      "The prompt names another column as an input but never uses it in any rule. Either the " +
      "reference is leftover, or a rule that should use it is missing.",
  },
  FALLBACK_NOT_STATED_UNTYPED: {
    title: "Wrong silence state",
    body:
      "`Not stated` is offered in a column type that does not use it. It is reserved for Date, " +
      "Number, Currency, and Duration; elsewhere silence is `Not addressed`.",
  },
  FALLBACK_NOT_ADDRESSED_TYPED: {
    title: "Wrong silence state",
    body: "`Not addressed` is offered in a typed column, where the silence state is `Not stated`.",
  },
  FALLBACK_SYNONYM: {
    title: "Off-vocabulary silence",
    body:
      "The prompt offers a value like `N/A`, `None`, or `Unknown` instead of the controlled " +
      "vocabulary, so silence cannot be counted consistently.",
  },
  CLASSIFY_LABEL_NOT_CONFIGURED: {
    title: "Label not configured",
    body:
      "The prompt tells the model to return a label that is not in the column's configured option " +
      "set, so the answer cannot land in the cell.",
  },
  CONTROL_PLANE_NARRATIVE: {
    title: "Control-plane narrative",
    body: "The prompt explains process or intent where the model needs an instruction.",
  },
  PROMPT_LENGTH_ADVISORY: {
    title: "Long prompt",
    body: "Past the 6,000-character target. Still runs; harder to keep consistent.",
  },
  CONCEPT_NAME_VARIANT: {
    title: "Similar names, no shared concept",
    body: "Two rules in different modules look like the same idea but share no concept tag.",
  },
  CONCEPT_DIVERGENT_RULES: {
    title: "Same name, different rules",
    body: "One name used across modules with different types, options, or silence states.",
  },
  CURRENCY_PATTERN_DIVERGENT: {
    title: "Currency style differs",
    body: "A money format appears that is not the one the matter standard sets.",
  },
  COLUMN_NOT_VERIFIED: {
    title: "Not verified",
    body: "The rule has not been through a recorded test set.",
  },
  COLUMN_STALE: {
    title: "Stale",
    body: "The recorded result predates a change to this rule or something upstream of it.",
  },
};

export const lookup = (k: string | null | undefined): Entry | null =>
  (k && GLOSSARY[k]) || null;
