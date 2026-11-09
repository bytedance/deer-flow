import type { Message } from "@langchain/langgraph-sdk";

export type HumanInputMode =
  | "free_text"
  | "single_choice"
  | "choice_with_other"
  | "form";

export type HumanInputOption = {
  id: string;
  label: string;
  value: string;
};

export type HumanInputFieldType =
  | "text"
  | "textarea"
  | "number"
  | "select"
  | "multi_select"
  | "checkbox"
  | "date";

export type HumanInputField = {
  name: string;
  label: string;
  type: HumanInputFieldType;
  required: boolean;
  placeholder?: string;
  options?: HumanInputOption[];
};

export type HumanInputFormValue = string | number | boolean | string[];

export type HumanInputRequest = {
  version: 1 | 2;
  kind: "human_input_request";
  source: "ask_clarification" | string;
  request_id: string;
  tool_call_id?: string;
  clarification_type?: string;
  title?: string;
  question: string;
  context?: string | null;
  input_mode: HumanInputMode;
  options?: HumanInputOption[];
  fields?: HumanInputField[];
};

export type HumanInputResponse =
  | {
      version: 1;
      kind: "human_input_response";
      source: string;
      request_id: string;
      response_kind: "option";
      option_id: string;
      value: string;
    }
  | {
      version: 1;
      kind: "human_input_response";
      source: string;
      request_id: string;
      response_kind: "text";
      value: string;
    };

export type HitlApprovalDecision = "approve" | "reject";

export type HitlApprovalAction = {
  tool_call_id: string;
  tool_name: string;
  args_summary: string | Record<string, unknown>;
  request_id: string;
};

export type HitlApprovalRequest = {
  version: 1;
  kind: "hitl_approval";
  request_id: string;
  actions: HitlApprovalAction[];
  allowed_decisions: HitlApprovalDecision[];
  pending_tool_call_ids: string[];
};

export type HitlApprovalResponse = {
  version: 1;
  kind: "human_input_response";
  source: "hitl_approval";
  request_id: string;
  tool_call_id: string;
  response_kind: "option";
  option_id: HitlApprovalDecision;
  value: string;
};

export type HitlApprovalResume = { responses: HitlApprovalResponse[] };

export type HumanInputThreadState = {
  answeredResponses: Map<string, HumanInputResponse>;
  latestOpenRequestId: string | null;
};

export function shouldClearPendingHumanInputOnThreadError({
  currentError,
  pendingRequestCount,
  previousError,
}: {
  currentError: unknown;
  pendingRequestCount: number;
  previousError: unknown;
}) {
  return (
    pendingRequestCount > 0 &&
    currentError != null &&
    !Object.is(currentError, previousError)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isApprovalDecision(value: unknown): value is HitlApprovalDecision {
  return value === "approve" || value === "reject";
}

/** Parse only the approval interrupt payload; static breakpoints stay invisible. */
export function parseHitlApprovalRequest(
  value: unknown,
): HitlApprovalRequest | null {
  if (
    !isRecord(value) ||
    value.kind !== "hitl_approval" ||
    value.version !== 1 ||
    !isNonEmptyString(value.request_id) ||
    !Array.isArray(value.actions) ||
    value.actions.length === 0 ||
    !Array.isArray(value.allowed_decisions) ||
    !Array.isArray(value.pending_tool_call_ids)
  ) {
    return null;
  }

  const allowedDecisions = value.allowed_decisions.filter(isApprovalDecision);
  if (
    allowedDecisions.length === 0 ||
    allowedDecisions.length !== value.allowed_decisions.length ||
    new Set(allowedDecisions).size !== allowedDecisions.length
  ) {
    return null;
  }

  const actions: HitlApprovalAction[] = [];
  const toolCallIds = new Set<string>();
  const requestIds = new Set<string>();
  for (const action of value.actions) {
    if (
      !isRecord(action) ||
      !isNonEmptyString(action.tool_call_id) ||
      !isNonEmptyString(action.tool_name) ||
      (typeof action.args_summary !== "string" &&
        !isRecord(action.args_summary)) ||
      !isNonEmptyString(action.request_id) ||
      toolCallIds.has(action.tool_call_id) ||
      requestIds.has(action.request_id)
    ) {
      return null;
    }
    toolCallIds.add(action.tool_call_id);
    requestIds.add(action.request_id);
    actions.push({
      tool_call_id: action.tool_call_id,
      tool_name: action.tool_name,
      args_summary: action.args_summary,
      request_id: action.request_id,
    });
  }

  if (
    value.pending_tool_call_ids.length !== actions.length ||
    value.pending_tool_call_ids.some(
      (id) => typeof id !== "string" || !toolCallIds.has(id),
    ) ||
    new Set(value.pending_tool_call_ids).size !== actions.length
  ) {
    return null;
  }

  return {
    version: 1,
    kind: "hitl_approval",
    request_id: value.request_id,
    actions,
    allowed_decisions: allowedDecisions,
    pending_tool_call_ids: [...value.pending_tool_call_ids] as string[],
  };
}

/** Accept SDK live Interrupt objects and REST Record<task, Interrupt[]> shapes. */
export function extractHitlApprovalRequests(source: unknown) {
  const candidates: unknown[] = Array.isArray(source) ? source : [source];
  const requests: HitlApprovalRequest[] = [];
  const seen = new Set<string>();
  const append = (candidate: unknown): void => {
    if (Array.isArray(candidate)) {
      candidate.forEach(append);
      return;
    }
    if (!isRecord(candidate)) return;
    const value = "value" in candidate ? candidate.value : candidate;
    if (Array.isArray(value)) {
      value.forEach(append);
      return;
    }
    const request = parseHitlApprovalRequest(value);
    if (request && !seen.has(request.request_id)) {
      seen.add(request.request_id);
      requests.push(request);
    }
  };

  for (const candidate of candidates) {
    if (
      isRecord(candidate) &&
      candidate.kind !== "hitl_approval" &&
      !("value" in candidate)
    ) {
      for (const interrupts of Object.values(candidate)) {
        if (Array.isArray(interrupts)) interrupts.forEach(append);
      }
    } else {
      append(candidate);
    }
  }
  return requests;
}

/** Build one atomic resume batch, or null while any action is undecided. */
export function createHitlApprovalResponses(
  request: HitlApprovalRequest,
  decisions: Readonly<Record<string, HitlApprovalDecision | undefined>>,
  rejectionReason = "",
): HitlApprovalResponse[] | null {
  const responses: HitlApprovalResponse[] = [];
  for (const action of request.actions) {
    const decision = decisions[action.tool_call_id];
    if (!decision || !request.allowed_decisions.includes(decision)) return null;
    responses.push({
      version: 1,
      kind: "human_input_response",
      source: "hitl_approval",
      request_id: action.request_id,
      tool_call_id: action.tool_call_id,
      response_kind: "option",
      option_id: decision,
      value: decision === "reject" ? rejectionReason : "",
    });
  }
  return responses;
}

export function parseApprovalArgsSummary(summary: unknown) {
  if (isRecord(summary)) return summary;
  if (typeof summary !== "string") return { summary: String(summary) };
  try {
    const parsed: unknown = JSON.parse(summary);
    if (isRecord(parsed)) return parsed;
  } catch {
    // The backend serializes its flat string map with Python repr.
  }
  return parsePythonStringDict(summary) ?? { summary };
}

const PYTHON_STRING_ESCAPES: Record<string, string> = {
  "\\": "\\",
  "'": "'",
  '"': '"',
  a: "\u0007",
  b: "\b",
  f: "\f",
  n: "\n",
  r: "\r",
  t: "\t",
  v: "\v",
  "\n": "",
};
function readPythonQuotedString(text: string, start: number) {
  const quote = text[start];
  if (quote !== "'" && quote !== '"') return null;
  let value = "";
  let index = start + 1;
  while (index < text.length) {
    const char = text[index++]!;
    if (char === quote) return { value, end: index };
    if (char !== "\\") {
      value += char;
      continue;
    }
    if (index >= text.length) return null;
    const escape = text[index++]!;
    if (escape in PYTHON_STRING_ESCAPES) {
      value += PYTHON_STRING_ESCAPES[escape];
      continue;
    }
    const hexLength =
      escape === "x" ? 2 : escape === "u" ? 4 : escape === "U" ? 8 : 0;
    if (hexLength > 0) {
      const hex = text.slice(index, index + hexLength);
      if (hex.length !== hexLength || !/^[0-9a-fA-F]+$/.test(hex)) return null;
      const codePoint = Number.parseInt(hex, 16);
      if (codePoint > 0x10ffff) return null;
      value += String.fromCodePoint(codePoint);
      index += hexLength;
      continue;
    }
    if (/^[0-7]$/.test(escape)) {
      let octal = escape;
      while (octal.length < 3 && /^[0-7]$/.test(text[index] ?? "")) {
        octal += text[index++]!;
      }
      value += String.fromCharCode(Number.parseInt(octal, 8));
      continue;
    }
    value += escape;
  }
  return null;
}

function parsePythonStringDict(text: string) {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{") || !trimmed.endsWith("}")) return null;
  const result: Record<string, unknown> = Object.create(null);
  let index = 1;
  const skipSpace = () => {
    while (/\s/.test(trimmed[index] ?? "")) index += 1;
  };
  while (index < trimmed.length - 1) {
    skipSpace();
    if (trimmed[index] === "}") return result;
    const key = readPythonQuotedString(trimmed, index);
    if (!key) return null;
    index = key.end;
    skipSpace();
    if (trimmed[index++] !== ":") return null;
    skipSpace();
    const value = readPythonQuotedString(trimmed, index);
    if (!value) return null;
    index = value.end;
    result[key.value] = value.value;
    skipSpace();
    if (trimmed[index] === "}") return result;
    if (trimmed[index++] !== ",") return null;
  }
  return index === trimmed.length - 1 ? result : null;
}

function isHumanInputMode(value: unknown): value is HumanInputMode {
  return (
    value === "free_text" ||
    value === "single_choice" ||
    value === "choice_with_other" ||
    value === "form"
  );
}

// Field names that collide with JavaScript Object.prototype members. Form
// values live in a plain object keyed by field name, so these would resolve
// to inherited properties instead of user input.
const RESERVED_FIELD_NAMES = new Set([
  "__proto__",
  "constructor",
  "prototype",
  "toString",
  "toLocaleString",
  "valueOf",
  "hasOwnProperty",
  "isPrototypeOf",
  "propertyIsEnumerable",
  "__defineGetter__",
  "__defineSetter__",
  "__lookupGetter__",
  "__lookupSetter__",
]);

export function readHumanInputFormValue(
  values: Record<string, HumanInputFormValue>,
  name: string,
): HumanInputFormValue | undefined {
  return Object.prototype.hasOwnProperty.call(values, name)
    ? values[name]
    : undefined;
}

export function buildInitialHumanInputFormValues(
  fields: HumanInputField[],
): Record<string, HumanInputFormValue> {
  // Checkboxes are booleans that default to an explicit "no" — without the
  // seed an untouched checkbox would be indistinguishable from an unanswered
  // field and silently vanish from the submitted summary.
  const values: Record<string, HumanInputFormValue> = {};
  for (const field of fields) {
    if (field.type === "checkbox") {
      values[field.name] = false;
    }
  }
  return values;
}

function isHumanInputFieldType(value: unknown): value is HumanInputFieldType {
  return (
    value === "text" ||
    value === "textarea" ||
    value === "number" ||
    value === "select" ||
    value === "multi_select" ||
    value === "checkbox" ||
    value === "date"
  );
}

function readOptionalString(value: unknown) {
  return typeof value === "string" ? value : undefined;
}

function parseOptions(value: unknown): HumanInputOption[] | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (!Array.isArray(value)) {
    return undefined;
  }

  const options: HumanInputOption[] = [];
  const seenIds = new Set<string>();
  const seenValues = new Set<string>();
  for (const option of value) {
    if (!isRecord(option)) {
      return undefined;
    }
    const id = option.id;
    const label = option.label;
    const optionValue = option.value;
    if (
      !isNonEmptyString(id) ||
      !isNonEmptyString(label) ||
      // An empty option value crashes Radix <SelectItem value="">; a
      // malformed/replayed artifact must fall back to plain text instead.
      !isNonEmptyString(optionValue) ||
      seenIds.has(id) ||
      seenValues.has(optionValue)
    ) {
      return undefined;
    }
    seenIds.add(id);
    seenValues.add(optionValue);
    options.push({ id, label, value: optionValue });
  }
  return options;
}

function parseFields(value: unknown): HumanInputField[] | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (!Array.isArray(value)) {
    return undefined;
  }

  const fields: HumanInputField[] = [];
  const seenNames = new Set<string>();
  for (const field of value) {
    if (!isRecord(field)) {
      return undefined;
    }
    const name = field.name;
    if (typeof name === "string" && seenNames.has(name)) {
      return undefined;
    }
    if (typeof name === "string") {
      seenNames.add(name);
    }
    const label = field.label;
    const type = field.type;
    const required = field.required;
    if (
      !isNonEmptyString(name) ||
      RESERVED_FIELD_NAMES.has(name) ||
      !isNonEmptyString(label) ||
      !isHumanInputFieldType(type) ||
      (required !== undefined && typeof required !== "boolean")
    ) {
      return undefined;
    }
    const options = parseOptions(field.options);
    if (field.options !== undefined && options === undefined) {
      return undefined;
    }
    if (
      (type === "select" || type === "multi_select") &&
      (!options || options.length === 0)
    ) {
      return undefined;
    }
    fields.push({
      name,
      label,
      type,
      required: required === true,
      ...(readOptionalString(field.placeholder)
        ? { placeholder: readOptionalString(field.placeholder) }
        : {}),
      ...(options ? { options } : {}),
    });
  }
  return fields;
}

export function parseHumanInputRequest(
  value: unknown,
): HumanInputRequest | null {
  if (!isRecord(value)) {
    return null;
  }
  if (
    (value.version !== 1 && value.version !== 2) ||
    value.kind !== "human_input_request" ||
    !isNonEmptyString(value.source) ||
    !isNonEmptyString(value.request_id) ||
    !isNonEmptyString(value.question) ||
    !isHumanInputMode(value.input_mode)
  ) {
    return null;
  }

  const options = parseOptions(value.options);
  if (value.options !== undefined && options === undefined) {
    return null;
  }
  if (
    (value.input_mode === "single_choice" ||
      value.input_mode === "choice_with_other") &&
    (!options || options.length === 0)
  ) {
    return null;
  }

  const fields = parseFields(value.fields);
  if (value.fields !== undefined && fields === undefined) {
    return null;
  }
  if (value.input_mode === "form" && (!fields || fields.length === 0)) {
    return null;
  }
  // Version/mode binding: `form` is a v2 construct and v2 defines nothing
  // else — a mismatched pair is a malformed payload, not a variant.
  if ((value.input_mode === "form") !== (value.version === 2)) {
    return null;
  }

  const context = value.context;
  if (
    context !== undefined &&
    context !== null &&
    typeof context !== "string"
  ) {
    return null;
  }

  return {
    version: value.version,
    kind: "human_input_request",
    source: value.source,
    request_id: value.request_id,
    ...(readOptionalString(value.tool_call_id)
      ? { tool_call_id: readOptionalString(value.tool_call_id) }
      : {}),
    ...(readOptionalString(value.clarification_type)
      ? { clarification_type: readOptionalString(value.clarification_type) }
      : {}),
    ...(readOptionalString(value.title)
      ? { title: readOptionalString(value.title) }
      : {}),
    question: value.question,
    ...(context !== undefined ? { context } : {}),
    input_mode: value.input_mode,
    ...(options ? { options } : {}),
    ...(fields ? { fields } : {}),
  };
}

export function parseHumanInputResponse(
  value: unknown,
): HumanInputResponse | null {
  if (!isRecord(value)) {
    return null;
  }
  if (
    value.version !== 1 ||
    value.kind !== "human_input_response" ||
    !isNonEmptyString(value.source) ||
    !isNonEmptyString(value.request_id) ||
    !isNonEmptyString(value.value)
  ) {
    return null;
  }

  if (value.response_kind === "option") {
    if (!isNonEmptyString(value.option_id)) {
      return null;
    }
    return {
      version: 1,
      kind: "human_input_response",
      source: value.source,
      request_id: value.request_id,
      response_kind: "option",
      option_id: value.option_id,
      value: value.value,
    };
  }

  if (value.response_kind === "text") {
    return {
      version: 1,
      kind: "human_input_response",
      source: value.source,
      request_id: value.request_id,
      response_kind: "text",
      value: value.value,
    };
  }

  return null;
}

export function extractHumanInputRequest(
  message: Message,
): HumanInputRequest | null {
  if (message.type !== "tool") {
    return null;
  }
  const artifact = Reflect.get(message, "artifact");
  if (!isRecord(artifact)) {
    return null;
  }
  return parseHumanInputRequest(artifact.human_input);
}

export function extractHumanInputResponse(
  message: Message,
): HumanInputResponse | null {
  if (message.type !== "human") {
    return null;
  }
  const additionalKwargs = message.additional_kwargs;
  if (!isRecord(additionalKwargs)) {
    return null;
  }
  return parseHumanInputResponse(additionalKwargs.human_input_response);
}

function extractPlainMessageText(message: Message): string {
  const content: unknown = message.content;
  if (typeof content === "string") {
    return content.trim();
  }
  if (Array.isArray(content)) {
    return content
      .map((part) =>
        isRecord(part) && part.type === "text" && typeof part.text === "string"
          ? part.text
          : "",
      )
      .join("")
      .trim();
  }
  return "";
}

export function deriveHumanInputThreadState(
  messages: Message[],
  isVisibleMessage: (message: Message) => boolean = (message) =>
    message.additional_kwargs?.hide_from_ui !== true,
): HumanInputThreadState {
  const answeredResponses = new Map<string, HumanInputResponse>();
  const seenRequests = new Map<string, HumanInputRequest>();
  const requestOrder: string[] = [];

  for (const message of messages) {
    if (isVisibleMessage(message)) {
      const request = extractHumanInputRequest(message);
      if (request) {
        seenRequests.set(request.request_id, request);
        requestOrder.push(request.request_id);
      }
    }

    const response = extractHumanInputResponse(message);
    if (
      response &&
      seenRequests.has(response.request_id) &&
      !answeredResponses.has(response.request_id)
    ) {
      answeredResponses.set(response.request_id, response);
      continue;
    }

    // Legacy-frontend fallback: a v1-only frontend renders a v2 request as
    // plain text and the user answers through the normal composer, so the
    // reply carries no human_input_response metadata. The reply closes only
    // the LATEST unanswered request — the one the user was presumably
    // answering. Nothing guarantees at most one outstanding request across
    // runs, and closing them all would silently swallow older decisions with
    // the same text; an older request left open simply becomes the active
    // card again.
    if (message.type === "human" && isVisibleMessage(message) && !response) {
      const latestUnansweredId = [...requestOrder]
        .reverse()
        .find((requestId) => !answeredResponses.has(requestId));
      const request =
        latestUnansweredId === undefined
          ? undefined
          : seenRequests.get(latestUnansweredId);
      if (latestUnansweredId !== undefined && request) {
        answeredResponses.set(latestUnansweredId, {
          version: 1,
          kind: "human_input_response",
          source: request.source,
          request_id: latestUnansweredId,
          response_kind: "text",
          value: extractPlainMessageText(message) || "-",
        });
      }
    }
  }

  const latestOpenRequestId =
    [...requestOrder]
      .reverse()
      .find((requestId) => !answeredResponses.has(requestId)) ?? null;

  return { answeredResponses, latestOpenRequestId };
}

export function hasOpenHumanInputRequest(
  messages: Message[],
  isVisibleMessage?: (message: Message) => boolean,
) {
  return (
    deriveHumanInputThreadState(messages, isVisibleMessage)
      .latestOpenRequestId !== null
  );
}

export function createHumanInputOptionResponse(
  request: HumanInputRequest,
  option: HumanInputOption,
): HumanInputResponse {
  return {
    version: 1,
    kind: "human_input_response",
    source: request.source,
    request_id: request.request_id,
    response_kind: "option",
    option_id: option.id,
    value: option.value,
  };
}

function formatFormValue(value: HumanInputFormValue) {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  return String(value);
}

function isEmptyFormValue(value: HumanInputFormValue | undefined) {
  if (value === undefined) {
    return true;
  }
  if (typeof value === "string") {
    return value.trim().length === 0;
  }
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  return false;
}

export function buildHumanInputFormSummary(
  request: HumanInputRequest,
  values: Record<string, HumanInputFormValue>,
) {
  const fields = request.fields ?? [];
  const parts: string[] = [];
  for (const field of fields) {
    const value = readHumanInputFormValue(values, field.name);
    if (isEmptyFormValue(value)) {
      continue;
    }
    parts.push(`${field.label}: ${formatFormValue(value!)}`);
  }
  return parts.join("; ");
}

export function buildHumanInputFormSubmissionValue(
  request: HumanInputRequest,
  values: Record<string, HumanInputFormValue>,
) {
  // The readable summary alone is ambiguous ("a: x; B: y" could come from
  // several field mappings), so the submitted value appends the full record
  // as one JSON block keyed by stable field names — labels/names may contain
  // the separators themselves, so only whole-record JSON is collision-free.
  const record: Record<string, HumanInputFormValue> = {};
  for (const field of request.fields ?? []) {
    const value = readHumanInputFormValue(values, field.name);
    if (isEmptyFormValue(value)) {
      continue;
    }
    record[field.name] = value!;
  }
  return `${buildHumanInputFormSummary(request, values)} [values: ${JSON.stringify(record)}]`;
}

export function createHumanInputTextResponse(
  request: HumanInputRequest,
  value: string,
): HumanInputResponse {
  return {
    version: 1,
    kind: "human_input_response",
    source: request.source,
    request_id: request.request_id,
    response_kind: "text",
    value,
  };
}

export function buildHumanInputResponseText(
  request: HumanInputRequest,
  response: HumanInputResponse,
) {
  return `For your clarification "${request.question}", my answer is: ${response.value}`;
}
