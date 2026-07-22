package com.deerflow.mobile.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import org.junit.Rule
import org.junit.Test

class LoginSnackbarHostTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun rendersAuthenticationErrorsBeforeTheWorkspaceIsAvailable() {
        compose.setContent {
            val snackbar = remember { SnackbarHostState() }
            LaunchedEffect(Unit) {
                snackbar.showSnackbar("Sign-in failed. Check the server address.")
            }
            MaterialTheme {
                LoginSnackbarHost(snackbar)
            }
        }

        compose.onNodeWithText("Sign-in failed. Check the server address.").assertIsDisplayed()
    }
}
