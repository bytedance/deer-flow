@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.deerflow.mobile.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.width
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.rememberDrawerState
import androidx.compose.material3.DrawerValue
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val DRAWER_NAVIGATION_LEAD_MILLIS = 72L

@Composable
fun WorkspaceShell(state: AppUiState, viewModel: AppViewModel, snackbar: SnackbarHostState) {
    BoxWithConstraints(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        val expanded = maxWidth >= 840.dp
        if (expanded) {
            ExpandedWorkspace(state, viewModel, snackbar)
        } else {
            CompactWorkspace(state, viewModel, snackbar, drawerWidth = maxWidth * 0.8f)
        }
    }
}

@Composable
private fun CompactWorkspace(
    state: AppUiState,
    viewModel: AppViewModel,
    snackbar: SnackbarHostState,
    drawerWidth: Dp,
) {
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val focusManager = LocalFocusManager.current
    val keyboardController = LocalSoftwareKeyboardController.current
    var showSkills by remember { mutableStateOf(false) }
    var drawerNavigationInProgress by remember { mutableStateOf(false) }

    fun navigateWithDrawerExit(overlapDrawerExit: Boolean = true, destination: () -> Unit) {
        if (drawerNavigationInProgress) return

        drawerNavigationInProgress = true
        focusManager.clearFocus(force = true)
        keyboardController?.hide()
        scope.launch {
            try {
                val drawerCloseJob = launch { drawerState.close() }
                if (overlapDrawerExit) {
                    delay(DRAWER_NAVIGATION_LEAD_MILLIS)
                } else {
                    drawerCloseJob.join()
                }
                destination()
                drawerCloseJob.join()
            } finally {
                drawerNavigationInProgress = false
            }
        }
    }

    LaunchedEffect(drawerState.currentValue) {
        if (drawerState.currentValue == DrawerValue.Open) {
            focusManager.clearFocus(force = true)
            keyboardController?.hide()
        }
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModalDrawerSheet(modifier = Modifier.width(drawerWidth)) {
                WorkspaceDrawer(
                    state = state,
                    onNewChat = {
                        navigateWithDrawerExit(destination = viewModel::createThread)
                    },
                    onOpenThread = {
                        navigateWithDrawerExit { viewModel.openThread(it) }
                    },
                    onRenameThread = viewModel::renameThread,
                    onDeleteThread = viewModel::deleteThread,
                    onPinThread = viewModel::toggleThreadPinned,
                    onOpenProfile = {
                        navigateWithDrawerExit {
                            viewModel.openWorkspaceChild(AppRoute.Profile)
                        }
                    },
                    drawerOpen = drawerState.currentValue == DrawerValue.Open,
                    onDestination = { destination ->
                        when (destination) {
                            DrawerDestination.Agents -> navigateWithDrawerExit {
                                viewModel.openWorkspaceChild(AppRoute.Agents)
                            }
                            DrawerDestination.Tasks -> navigateWithDrawerExit {
                                viewModel.openWorkspaceChild(AppRoute.Tasks)
                            }
                            DrawerDestination.Skills -> navigateWithDrawerExit(overlapDrawerExit = false) {
                                showSkills = true
                                viewModel.refreshMcpConfig()
                                viewModel.refreshMcpTools()
                            }
                            DrawerDestination.Memory -> navigateWithDrawerExit {
                                viewModel.openWorkspaceChild(AppRoute.Memory)
                            }
                            DrawerDestination.NewConversation -> navigateWithDrawerExit {
                                viewModel.closeConversation()
                            }
                            else -> Unit
                        }
                    },
                )
            }
        },
    ) {
        Scaffold(
            contentWindowInsets = WindowInsets(0, 0, 0, 0),
            containerColor = MaterialTheme.colorScheme.background,
            snackbarHost = { SnackbarHost(snackbar) },
        ) { padding ->
            Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
                WorkspacePage(
                    state,
                    viewModel,
                    onOpenDrawer = {
                        focusManager.clearFocus(force = true)
                        keyboardController?.hide()
                        scope.launch { drawerState.open() }
                    },
                    contentPadding = padding,
                )
            }
        }
    }
    if (showSkills) SkillsSheet(state, viewModel, onDismiss = { showSkills = false })
}

@Composable
private fun ExpandedWorkspace(state: AppUiState, viewModel: AppViewModel, snackbar: SnackbarHostState) {
    var showSkills by remember { mutableStateOf(false) }
    androidx.compose.foundation.layout.Row(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        Box(Modifier.width(320.dp)) {
            WorkspaceDrawer(
                state = state,
                onNewChat = viewModel::createThread,
                onOpenThread = viewModel::openThread,
                onRenameThread = viewModel::renameThread,
                onDeleteThread = viewModel::deleteThread,
                onPinThread = viewModel::toggleThreadPinned,
                onOpenProfile = { viewModel.openWorkspaceChild(AppRoute.Profile) },
                onDestination = { destination ->
                    when (destination) {
                        DrawerDestination.Agents -> viewModel.openWorkspaceChild(AppRoute.Agents)
                        DrawerDestination.Tasks -> viewModel.openWorkspaceChild(AppRoute.Tasks)
                        DrawerDestination.Skills -> {
                            showSkills = true
                            viewModel.refreshMcpConfig()
                            viewModel.refreshMcpTools()
                        }
                        DrawerDestination.Memory -> viewModel.openWorkspaceChild(AppRoute.Memory)
                        else -> Unit
                    }
                },
            )
        }
        Scaffold(
            contentWindowInsets = WindowInsets(0, 0, 0, 0),
            containerColor = MaterialTheme.colorScheme.background,
            snackbarHost = { SnackbarHost(snackbar) },
        ) { padding ->
            WorkspacePage(state, viewModel, onOpenDrawer = {}, contentPadding = padding)
        }
    }
    if (showSkills) SkillsSheet(state, viewModel, onDismiss = { showSkills = false })
}

@Composable
private fun WorkspacePage(
    state: AppUiState,
    viewModel: AppViewModel,
    onOpenDrawer: () -> Unit,
    contentPadding: androidx.compose.foundation.layout.PaddingValues,
) {
    AnimatedContent(
        targetState = state.route,
        modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background),
        transitionSpec = {
            val enteringDrawerDestination = targetState != AppRoute.Workspace
            (
                fadeIn(initialAlpha = 0.4f, animationSpec = tween(durationMillis = 210)) +
                    slideInHorizontally(
                        animationSpec = tween(durationMillis = 240),
                        initialOffsetX = { width -> if (enteringDrawerDestination) width / 6 else -width / 12 },
                    )
            ).togetherWith(
                fadeOut(animationSpec = tween(durationMillis = 120)) +
                    slideOutHorizontally(
                        animationSpec = tween(durationMillis = 180),
                        targetOffsetX = { width -> if (enteringDrawerDestination) -width / 12 else width / 12 },
                    ),
            )
        },
        contentKey = { it },
        label = "workspace-child-hero",
    ) { route ->
        Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
            when (route) {
                AppRoute.Workspace, AppRoute.Conversation -> ChatScreen(state, viewModel, onOpenDrawer, contentPadding)
                AppRoute.Agents -> AgentsScreen(state, viewModel, viewModel::closeWorkspaceChild, contentPadding)
                AppRoute.Tasks -> TasksScreen(state, viewModel, viewModel::closeWorkspaceChild, contentPadding)
                AppRoute.Memory -> MemoryScreen(
                    state = state,
                    onBack = viewModel::closeWorkspaceChild,
                    contentPadding = contentPadding,
                    onRefresh = viewModel::refreshMemory,
                    onSaveFact = viewModel::saveMemoryFact,
                    onDeleteFact = viewModel::deleteMemoryFact,
                    onClearMemory = viewModel::clearMemory,
                )
                AppRoute.Profile -> ProfileScreen(state, viewModel, viewModel::closeWorkspaceChild, contentPadding)
            }
        }
    }
}
