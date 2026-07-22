package com.deerflow.mobile.ui

import com.deerflow.mobile.data.AttachmentStatus
import com.deerflow.mobile.data.ComposerState
import com.deerflow.mobile.data.PendingAttachment
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MessageSubmissionTest {
    @Test
    fun gateRejectsDuplicateSendsUntilTheFirstSubmissionReleasesIt() {
        val gate = MessageSubmissionGate()

        assertTrue(gate.tryAcquire())
        assertFalse(gate.tryAcquire())
        gate.release()
        assertTrue(gate.tryAcquire())
    }

    @Test
    fun failedUploadRestoresDraftAndAttachmentsForRetry() {
        val composer = ComposerState(
            attachments = listOf(PendingAttachment("content://file", "brief.pdf", "application/pdf", 12)),
            uploading = true,
        )

        val restored = restoreFailedComposer(composer, "Summarize this", "Upload failed")

        assertEquals("Summarize this", restored.text)
        assertFalse(restored.uploading)
        assertEquals(AttachmentStatus.Failed, restored.attachments.single().status)
        assertEquals("Upload failed", restored.attachments.single().error)
    }
}
