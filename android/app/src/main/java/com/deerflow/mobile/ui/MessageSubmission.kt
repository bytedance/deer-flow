package com.deerflow.mobile.ui

import com.deerflow.mobile.data.AttachmentStatus
import com.deerflow.mobile.data.ComposerState

/** Serializes taps until the current prompt has entered the run coordinator. */
internal class MessageSubmissionGate {
    private var locked = false

    fun tryAcquire(): Boolean {
        if (locked) return false
        locked = true
        return true
    }

    fun release() {
        locked = false
    }
}

internal fun restoreFailedComposer(
    composer: ComposerState,
    text: String,
    attachmentError: String?,
): ComposerState = composer.copy(
    text = text,
    uploading = false,
    attachments = composer.attachments.map { attachment ->
        if (attachmentError == null) attachment else attachment.copy(status = AttachmentStatus.Failed, error = attachmentError)
    },
)
