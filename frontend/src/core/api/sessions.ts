import { getAPIClient } from "../api";

/**
 * Read the novel card (card.json) for a given thread.
 * The card is stored at <workspace>/book/<book_name>/card.json
 */
export async function getNovelCard(threadId: string): Promise<{
  book_name: string;
  genre: string;
  concept: string;
  platform: string;
  status: string;
  current_chapter: number;
  target_chapters: number;
  created_at: string;
}> {
  // First, list the book directory to discover the novel name
  const apiClient = getAPIClient();
  const listing = await (apiClient as any).run(
    "POST",
    `/api/threads/${threadId}/fs/ls`,
    {
      body: { path: "/book" },
    },
  );

  // listing should be an array of { name: string, type: string }
  let bookName = "";
  if (Array.isArray(listing) && listing.length > 0) {
    // pick the first book directory
    bookName = listing[0].name;
  }

  if (!bookName) {
    throw new Error("No book directory found in /book for thread " + threadId);
  }

  // Read card.json
  const cardPath = `/book/${bookName}/card.json`;
  const response = await fetch(
    `/api/threads/${threadId}/fs/read?${new URLSearchParams({ path: cardPath })}`,
  );

  if (!response.ok) {
    throw new Error(`Failed to read ${cardPath}: ${response.statusText}`);
  }

  return response.json();
}
