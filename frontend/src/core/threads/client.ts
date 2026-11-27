import type { Client } from "@langchain/langgraph-sdk/client";

import { getAPIClient } from "../api";

import { withHistoryErrorTagging } from "./history-error";
import { withRunErrorTagging } from "./run-error";
import { withThreadCreationTagging } from "./thread-creation";

/**
 * Tag a stream client so `onError` can tell which submission an error belongs
 * to.
 *
 * The SDK reports a refused run, a failed thread creation and a failed history
 * read the same way: through `onError` without run metadata. Each wrapper
 * records the identity its own call site knows, and `onError` settles the send
 * that produced the error instead of whichever send is mounted when it
 * surfaces (#8092 review).
 */
export function tagThreadClient(client: Client): Client {
  return withThreadCreationTagging(
    withRunErrorTagging(withHistoryErrorTagging(client)),
  );
}

/** The tagged client the thread stream uses. */
export function taggedThreadClient(isMock?: boolean): Client {
  return tagThreadClient(getAPIClient(isMock));
}
