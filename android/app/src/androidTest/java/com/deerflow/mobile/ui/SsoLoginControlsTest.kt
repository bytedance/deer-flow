package com.deerflow.mobile.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import com.deerflow.mobile.data.SsoProvider
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class SsoLoginControlsTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun ssoProviderButtonsRenderAndDispatchSelection() {
        var selected: SsoProvider? = null
        val provider = SsoProvider(id = "keycloak", displayName = "Company SSO")

        compose.setContent {
            MaterialTheme {
                SsoProviderButtons(
                    providers = listOf(provider),
                    loading = false,
                    enabled = true,
                    onProviderSelected = { selected = it },
                )
            }
        }

        compose.onNodeWithTag(UiTags.SsoProviderPrefix + "keycloak").assertIsDisplayed().performClick()
        compose.runOnIdle { assertEquals(provider, selected) }
    }
}
