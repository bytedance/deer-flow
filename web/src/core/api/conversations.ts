import type { Conversation } from "../messages";

import { resolveServiceURL } from "./resolve-service-url";

export async function queryConversations() {
    const response = await fetch(resolveServiceURL(`conversations?limit=100&sort=ts&offset=0`), {
        method: "GET",
        headers: {
            "Content-Type": "application/json",
        },
    })
        .then((res) => res.json())
        .then((res) => {
            return res.data ? res.data as Array<Conversation> : [];
        })
        .catch(() => {
            return [];
        });
    return response;
}

export async function querConversationById(thread_id: string) {
    const response = await fetch(resolveServiceURL(`conversation/${thread_id}`), {
        method: "GET",
        headers: {
            "Content-Type": "text/plain; charset=UTF-8",
        },
    })
        .then((res) => res.text())
        .then((res) => {
            return res;
        })
        .catch(() => {
            return "";
        });
    return response;
}


export async function queryConversationByPath(path: string, options: { abortSignal?: AbortSignal } = {},) {

    const response = await fetch(resolveServiceURL(`${path.substring(5)}`), {
        method: "GET",
        headers: {
            "Content-Type": "text/plain; charset=UTF-8",
        },
        signal: options.abortSignal,
    })
        .then((res) => res.text())
        .then((res) => {
            return res;
        })
        .catch(() => {
            return `Failed to fetch conversation by path: ${path}`;
        });

    return response;
}