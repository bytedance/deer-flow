@file:OptIn(
    androidx.compose.material3.ExperimentalMaterial3Api::class,
    androidx.compose.material3.ExperimentalMaterial3ExpressiveApi::class,
)

package com.deerflow.mobile.ui

import android.annotation.SuppressLint
import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.BackHandler
import androidx.activity.compose.PredictiveBackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LoadingIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.core.content.ContextCompat
import com.deerflow.mobile.R
import com.deerflow.mobile.data.SsoProvider
import com.deerflow.mobile.ui.theme.DeerFlowTheme
import com.deerflow.mobile.ui.theme.ExpressiveMotion

@Composable
fun DeerFlowApp(viewModel: AppViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val configuration = LocalConfiguration.current
    val notificationPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}
    LaunchedEffect(configuration.locales.toLanguageTags()) {
        viewModel.syncLanguagePreference()
    }
    LaunchedEffect(state.user, state.notifyOnRunCompletion) {
        if (
            state.user != null &&
            state.notifyOnRunCompletion &&
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
    DeerFlowTheme(state.theme, state.useDynamicColor) {
        val snackbar = remember { SnackbarHostState() }
        LaunchedEffect(state.error) {
            state.error?.let {
                snackbar.showSnackbar(it)
                viewModel.dismissError()
            }
        }
        LaunchedEffect(state.notice) {
            state.notice?.let {
                snackbar.showSnackbar(it)
                viewModel.dismissNotice()
            }
        }

        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.background,
        ) {
            Box(Modifier.fillMaxSize()) {
                AnimatedContent(
                    targetState = when {
                        state.checkingSession -> "loading"
                        state.user == null -> "login"
                        else -> "workspace"
                    },
                    modifier = Modifier.fillMaxSize(),
                    transitionSpec = {
                        (fadeIn(ExpressiveMotion.fastSpatial()) + scaleIn(ExpressiveMotion.spatial(), initialScale = 0.98f))
                            .togetherWith(fadeOut(ExpressiveMotion.fastSpatial()))
                    },
                    label = "session-screen",
                ) { screen ->
                    when (screen) {
                        "loading" -> LoadingScreen(state.serverUrl)
                        "login" -> LoginScreen(state, viewModel)
                        else -> AuthenticatedNavigation(state, viewModel, snackbar)
                    }
                }
                if (state.user == null) {
                    LoginSnackbarHost(
                        snackbar = snackbar,
                        modifier = Modifier.align(Alignment.BottomCenter).padding(24.dp),
                    )
                }
            }
        }
    }
}

@Composable
internal fun LoginSnackbarHost(snackbar: SnackbarHostState, modifier: Modifier = Modifier) {
    SnackbarHost(hostState = snackbar, modifier = modifier)
}

@Composable
private fun AuthenticatedNavigation(
    state: AppUiState,
    viewModel: AppViewModel,
    snackbar: SnackbarHostState,
) {
    PredictiveBackHandler(enabled = state.route == AppRoute.Conversation) { progress ->
        progress.collect {}
        viewModel.closeConversation()
    }
    PredictiveBackHandler(enabled = state.route.isWorkspaceChild) { progress ->
        progress.collect {}
        viewModel.closeWorkspaceChild()
    }
    // AppRoute is UI state, not a second navigation stack. Keeping one shell avoids
    // leaving a stale conversation destination behind after the top-bar back action.
    WorkspaceShell(state, viewModel, snackbar)
}


@Composable
private fun LoadingScreen(serverUrl: String) {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        BrandMark()
        Spacer(Modifier.height(28.dp))
        LoadingIndicator(Modifier.size(32.dp))
        Spacer(Modifier.height(16.dp))
        Text(serverUrl, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun LoginScreen(state: AppUiState, viewModel: AppViewModel) {
    state.ssoLoginProvider?.let { provider ->
        SsoLoginScreen(state, provider, viewModel)
        return
    }

    var email by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var serverUrl by rememberSaveable(state.serverUrl) { mutableStateOf(state.serverUrl) }
    val focusManager = LocalFocusManager.current
    val submit = {
        focusManager.clearFocus()
        if (serverUrl != state.serverUrl) viewModel.connectAndLogin(serverUrl, email, password)
        else viewModel.login(email, password)
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().testTag(UiTags.LoginScreen).imePadding(),
        contentPadding = PaddingValues(horizontal = 24.dp, vertical = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        item {
            Column(Modifier.widthIn(max = 480.dp).fillMaxWidth()) {
                BrandMark()
                Spacer(Modifier.height(32.dp))
                Text(stringResource(R.string.sign_in), style = MaterialTheme.typography.headlineMedium)
                Spacer(Modifier.height(8.dp))
                Text(
                    stringResource(R.string.login_subtitle),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(28.dp))
                OutlinedTextField(
                    value = serverUrl,
                    onValueChange = { serverUrl = it },
                    label = { Text(stringResource(R.string.server_address)) },
                    supportingText = { Text(stringResource(R.string.server_example)) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Next),
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = email,
                    onValueChange = { email = it },
                    label = { Text(stringResource(R.string.email)) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    label = { Text(stringResource(R.string.password)) },
                    visualTransformation = PasswordVisualTransformation(),
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                    keyboardActions = KeyboardActions(onDone = { submit() }),
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(20.dp))
                Button(
                    onClick = submit,
                    enabled = !state.loginBusy,
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                ) {
                    if (state.loginBusy) {
                        LoadingIndicator(Modifier.size(22.dp), color = MaterialTheme.colorScheme.onPrimary)
                    } else {
                        Text(if (serverUrl != state.serverUrl) stringResource(R.string.connect) else stringResource(R.string.sign_in))
                    }
                }
                Spacer(Modifier.height(12.dp))
                OutlinedButton(
                    onClick = { viewModel.saveServerUrl(serverUrl) },
                    enabled = !state.loginBusy,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(Icons.Outlined.Refresh, contentDescription = null)
                    Spacer(Modifier.height(0.dp))
                    Text(stringResource(R.string.check_server), modifier = Modifier.padding(start = 8.dp))
                }
                if (serverUrl == state.serverUrl) {
                    SsoProviderButtons(
                        providers = state.ssoProviders,
                        loading = state.loadingSsoProviders,
                        enabled = !state.loginBusy,
                        onProviderSelected = {
                            focusManager.clearFocus()
                            viewModel.beginSsoLogin(it)
                        },
                    )
                }
            }
        }
    }
}

@Composable
internal fun SsoProviderButtons(
    providers: List<SsoProvider>,
    loading: Boolean,
    enabled: Boolean,
    onProviderSelected: (SsoProvider) -> Unit,
) {
    if (!loading && providers.isEmpty()) return

    Column(Modifier.fillMaxWidth()) {
        Spacer(Modifier.height(20.dp))
        if (loading) LoadingIndicator(Modifier.size(24.dp).align(Alignment.CenterHorizontally))
        providers.forEach { provider ->
            Spacer(Modifier.height(12.dp))
            OutlinedButton(
                onClick = { onProviderSelected(provider) },
                enabled = enabled,
                modifier = Modifier.fillMaxWidth().testTag(UiTags.SsoProviderPrefix + provider.id),
            ) {
                Text(stringResource(R.string.continue_with_provider, provider.displayName))
            }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun SsoLoginScreen(
    state: AppUiState,
    provider: SsoProvider,
    viewModel: AppViewModel,
) {
    val loginUrl = remember(state.serverUrl, provider.id) { viewModel.ssoLoginUrl(provider) }
    var webView: WebView? by remember { mutableStateOf(null) }

    BackHandler { viewModel.cancelSsoLogin() }
    DisposableEffect(Unit) {
        onDispose {
            webView?.stopLoading()
            webView?.destroy()
        }
    }

    Column(Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = viewModel::cancelSsoLogin) {
                Icon(Icons.Outlined.ArrowBack, contentDescription = stringResource(R.string.back))
            }
            Text(
                stringResource(R.string.sso_web_title, provider.displayName),
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(start = 8.dp),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (state.checkingSsoSession) LoadingIndicator(Modifier.size(24.dp).align(Alignment.CenterHorizontally))
        AndroidView(
            factory = { context ->
                WebView(context).also { browser ->
                    webView = browser
                    browser.settings.apply {
                        javaScriptEnabled = true
                        domStorageEnabled = true
                        allowFileAccess = false
                        allowContentAccess = false
                        mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
                        mediaPlaybackRequiresUserGesture = true
                    }
                    browser.webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                            return request.url.scheme?.lowercase() !in setOf("http", "https")
                        }

                        override fun onPageFinished(view: WebView, url: String) {
                            super.onPageFinished(view, url)
                            viewModel.completeSsoLoginIfAvailable()
                        }
                    }
                    browser.loadUrl(loginUrl)
                }
            },
            modifier = Modifier.fillMaxSize().testTag(UiTags.SsoWebView),
        )
    }
}
