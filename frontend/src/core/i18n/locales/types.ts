import type { LucideIcon } from "lucide-react";

export interface Translations {
  // Locale meta
  locale: {
    localName: string;
  };

  // Common
  common: {
    home: string;
    settings: string;
    delete: string;
    edit: string;
    rename: string;
    share: string;
    openInNewWindow: string;
    close: string;
    more: string;
    search: string;
    loadMore: string;
    download: string;
    thinking: string;
    artifacts: string;
    public: string;
    custom: string;
    notAvailableInDemoMode: string;
    loading: string;
    version: string;
    lastUpdated: string;
    code: string;
    preview: string;
    cancel: string;
    save: string;
    install: string;
    create: string;
    import: string;
    export: string;
    exportAsMarkdown: string;
    exportAsJSON: string;
    exportSuccess: string;
  };

  home: {
    docs: string;
    blog: string;
  };

  // Welcome
  welcome: {
    greeting: string;
    description: string;
    createYourOwnSkill: string;
    createYourOwnSkillDescription: string;
  };

  // Greeting Card (personal-assistant-ux)
  greetingCard: {
    loading: string;
    defaultSuggestions: string[];
  };

  // Clipboard
  clipboard: {
    copyToClipboard: string;
    copiedToClipboard: string;
    failedToCopyToClipboard: string;
    linkCopied: string;
  };

  // Input Box
  inputBox: {
    placeholder: string;
    createSkillPrompt: string;
    addAttachments: string;
    inputSource: string;
    textInput: string;
    textInputDescription: string;
    microphoneInput: string;
    microphoneInputDescription: string;
    audioFileInput: string;
    audioFileInputDescription: string;
    audioFilePlaceholder: string;
    audioFileTranscribing: string;
    audioFileRetry: string;
    audioFileTranscriptionFailed: string;
    microphonePlaceholder: string;
    microphoneUnsupported: string;
    microphoneUnsupportedPlaceholder: string;
    mode: string;
    flashMode: string;
    flashModeDescription: string;
    reasoningMode: string;
    reasoningModeDescription: string;
    proMode: string;
    proModeDescription: string;
    ultraMode: string;
    ultraModeDescription: string;
    reasoningEffort: string;
    reasoningEffortMinimal: string;
    reasoningEffortMinimalDescription: string;
    reasoningEffortLow: string;
    reasoningEffortLowDescription: string;
    reasoningEffortMedium: string;
    reasoningEffortMediumDescription: string;
    reasoningEffortHigh: string;
    reasoningEffortHighDescription: string;
    searchModels: string;
    surpriseMe: string;
    surpriseMePrompt: string;
    followupLoading: string;
    followupConfirmTitle: string;
    followupConfirmDescription: string;
    followupConfirmAppend: string;
    followupConfirmReplace: string;
    knowledgeBase: string;
    suggestions: {
      suggestion: string;
      prompt: string;
      icon: LucideIcon;
    }[];
    suggestionsCreate: (
      | {
          suggestion: string;
          prompt: string;
          icon: LucideIcon;
        }
      | {
          type: "separator";
        }
    )[];
  };

  // Sidebar
  sidebar: {
    recentChats: string;
    newChat: string;
    chats: string;
    demoChats: string;
    agents: string;
    knowledgeBases: string;
    a2uiDebug: string;
  };

  // Agents
  agents: {
    title: string;
    description: string;
    newAgent: string;
    emptyTitle: string;
    emptyDescription: string;
    chat: string;
    delete: string;
    deleteConfirm: string;
    deleteSuccess: string;
    newChat: string;
    createPageTitle: string;
    createPageSubtitle: string;
    nameStepTitle: string;
    nameStepHint: string;
    nameStepPlaceholder: string;
    nameStepContinue: string;
    templateLabel: string;
    nameStepInvalidError: string;
    nameStepAlreadyExistsError: string;
    nameStepNetworkError: string;
    nameStepCheckError: string;
    nameStepApiDisabledError: string;
    nameStepBootstrapMessage: string;
    save: string;
    saving: string;
    saveRequested: string;
    saveHint: string;
    saveCommandMessage: string;
    agentCreatedPendingRefresh: string;
    more: string;
    agentCreated: string;
    startChatting: string;
    backToGallery: string;
  };

  // Knowledge Base
  knowledgeBase: {
    title: string;
    description: string;
    newKnowledgeBase: string;
    emptyTitle: string;
    emptyDescription: string;
    name: string;
    namePlaceholder: string;
    descriptionLabel: string;
    descriptionPlaceholder: string;
    visibility: string;
    visibilityPrivate: string;
    visibilityShared: string;
    status: string;
    statusActive: string;
    statusIndexing: string;
    statusError: string;
    documents: string;
    chunks: string;
    lastIndexed: string;
    never: string;
    create: string;
    creating: string;
    save: string;
    saving: string;
    delete: string;
    deleteConfirm: string;
    deleteSuccess: string;
    documentCount: string;
    addDocument: string;
    documentTitle: string;
    documentTitlePlaceholder: string;
    documentContent: string;
    documentContentPlaceholder: string;
    documentFormat: string;
    documentSource: string;
    documentSourcePlaceholder: string;
    reindex: string;
    reindexing: string;
    editDocument: string;
    deleteDocument: string;
    deleteDocumentConfirm: string;
    searchPlaceholder: string;
    searchButton: string;
    searching: string;
    noResults: string;
    searchResults: string;
    uploadFile: string;
    uploadFilePlaceholder: string;
    uploading: string;
    uploadSuccess: string;
    textInput: string;
    fileUpload: string;
    // Visibility (multi-level)
    visibilityTenant: string;
    visibilityPublic: string;
    // Permissions
    permissions: string;
    permissionsDescription: string;
    roleViewer: string;
    roleEditor: string;
    roleAdmin: string;
    grantPermission: string;
    revokePermission: string;
    revokeConfirm: string;
    noPermissions: string;
    userIdPlaceholder: string;
    selectRole: string;
    grantSuccess: string;
    revokeSuccess: string;
    myRole: string;
    // Tabs
    tabAll: string;
    tabMine: string;
    tabTenant: string;
    tabPublic: string;
    tabAdmin: string;
    groupMine: string;
    groupTenant: string;
    groupPublic: string;
    visibilityHintTenant: string;
    visibilityHintPublic: string;
    // Index progress
    indexingInProgress: string;
    indexComplete: string;
    indexFailed: string;
    // Index health
    indexHealth: string;
    indexedCount: string;
    failedCount: string;
    pendingCount: string;
    indexingCount: string;
    indexDuration: string;
    retrievalLatency: string;
    retrievalLatencyAvg: string;
    totalQueries: string;
    noIndexData: string;
  };

  // Breadcrumb
  breadcrumb: {
    workspace: string;
    chats: string;
  };

  // Workspace
  workspace: {
    officialWebsite: string;
    githubTooltip: string;
    settingsAndMore: string;
    visitGithub: string;
    reportIssue: string;
    contactUs: string;
    about: string;
    logout: string;
    guestUser: string;
  };

  // Conversation
  conversation: {
    noMessages: string;
    startConversation: string;
  };

  // Chats
  chats: {
    searchChats: string;
  };

  // Page titles (document title)
  pages: {
    appName: string;
    chats: string;
    newChat: string;
    untitled: string;
  };

  // Tool calls
  toolCalls: {
    moreSteps: (count: number) => string;
    lessSteps: string;
    executeCommand: string;
    presentFiles: string;
    needYourHelp: string;
    useTool: (toolName: string) => string;
    preparingForm: string;
    searchForRelatedInfo: string;
    searchForRelatedImages: string;
    searchFor: (query: string) => string;
    searchForRelatedImagesFor: (query: string) => string;
    searchOnWebFor: (query: string) => string;
    viewWebPage: string;
    listFolder: string;
    readFile: string;
    writeFile: string;
    clickToViewContent: string;
    writeTodos: string;
    skillInstallTooltip: string;
    generationProcess: string;
    generationProcessSteps: (count: number) => string;
  };

  // Uploads
  uploads: {
    uploading: string;
    uploadingFiles: string;
  };

  // Failure classification (ISSUE-02)
  failure: {
    execution_failed: string;
    upload_failed: string;
    external_dependency_unavailable: string;
    action_retry: string;
    action_reupload: string;
    action_wait_retry: string;
    layer_runtime: string;
    layer_gateway: string;
    layer_external: string;
  };

  // Empathetic error handling (personal-assistant-ux)
  errors: {
    network_issue: string;
    timeout: string;
    service_unavailable: string;
    data_not_found: string;
    permission_denied: string;
    rate_limited: string;
    quota_daily_exceeded: (used: number, limit: number) => string;
    quota_monthly_exceeded: (used: number, limit: number) => string;
    showDetails: string;
    hideDetails: string;
    retry: string;
    technicalDetails: string;
  };

  // Budget indicator (sidebar)
  budget: {
    today: string;
    thisMonth: string;
    todayUsage: string;
    monthlyUsage: string;
    used: string;
    of: string;
    remaining: string;
    warning: string;
    approachingLimit: string;
    limitReached: string;
    contactAdmin: string;
  };

  // Assistant status indicators (personal-assistant-ux)
  statusIndicators: {
    thinking: string;
    queryingData: string;
    generatingReport: string;
    analyzing: string;
  };

  // Subtasks
  subtasks: {
    subtask: string;
    executing: (count: number) => string;
    in_progress: string;
    completed: string;
    failed: string;
  };

  // Token Usage
  tokenUsage: {
    title: string;
    label: string;
    input: string;
    output: string;
    total: string;
    view: string;
    unavailable: string;
    unavailableShort: string;
    note: string;
    presets: {
      off: string;
      summary: string;
      perTurn: string;
      debug: string;
    };
    presetDescriptions: {
      off: string;
      summary: string;
      perTurn: string;
      debug: string;
    };
    finalAnswer: string;
    stepTotal: string;
    sharedAttribution: string;
    subagent: (description: string) => string;
    startTodo: (content: string) => string;
    completeTodo: (content: string) => string;
    updateTodo: (content: string) => string;
    removeTodo: (content: string) => string;
  };

  // Todo Counts (待办数量)
  todoCounts: {
    anomalyPending: string;
    startupPending: string;
    shutdownPending: string;
    loading: string;
    unavailable: string;
  };

  // Shortcuts
  shortcuts: {
    searchActions: string;
    noResults: string;
    actions: string;
    keyboardShortcuts: string;
    keyboardShortcutsDescription: string;
    openCommandPalette: string;
    toggleSidebar: string;
  };

  // Settings
  settings: {
    title: string;
    description: string;
    sections: {
      account: string;
      appearance: string;
      budget: string;
      memory: string;
      tools: string;
      skills: string;
      agents: string;
      notification: string;
      about: string;
    };
    memory: {
      title: string;
      description: string;
      empty: string;
      rawJson: string;
      exportButton: string;
      exportSuccess: string;
      importButton: string;
      importConfirmTitle: string;
      importConfirmDescription: string;
      importFileLabel: string;
      importInvalidFile: string;
      importSuccess: string;
      manualFactSource: string;
      addFact: string;
      addFactTitle: string;
      editFactTitle: string;
      addFactSuccess: string;
      editFactSuccess: string;
      clearAll: string;
      clearAllConfirmTitle: string;
      clearAllConfirmDescription: string;
      clearAllSuccess: string;
      factDeleteConfirmTitle: string;
      factDeleteConfirmDescription: string;
      factDeleteSuccess: string;
      factContentLabel: string;
      factCategoryLabel: string;
      factConfidenceLabel: string;
      factContentPlaceholder: string;
      factCategoryPlaceholder: string;
      factConfidenceHint: string;
      factSave: string;
      factValidationContent: string;
      factValidationConfidence: string;
      noFacts: string;
      summaryReadOnly: string;
      memoryFullyEmpty: string;
      factPreviewLabel: string;
      searchPlaceholder: string;
      filterAll: string;
      filterFacts: string;
      filterSummaries: string;
      noMatches: string;
      memoryUiDisabled: string;
      tabs: {
        user: string;
        session: string;
        domain: string;
      };
      toggles: {
        user: string;
        session: string;
        domain: string;
      };
      errorPrefix: string;
      domain: {
        searchPlaceholder: string;
        domainFilterPlaceholder: string;
        entityFilterPlaceholder: string;
        searchButton: string;
        createFact: string;
        exportButton: string;
        searchRequired: string;
        exportSuccess: string;
        createRequired: string;
        createSuccess: string;
        emptyState: string;
        searching: string;
        noMatches: string;
        resultCount: string;
        confidenceLabel: string;
        createdLabel: string;
        scoreLabel: string;
        createDialogTitle: string;
        contentLabel: string;
        contentPlaceholder: string;
        domainLabel: string;
        domainPlaceholder: string;
        entityIdLabel: string;
        entityIdPlaceholder: string;
        confidenceFieldLabel: string;
        cancelButton: string;
        createButton: string;
        creatingButton: string;
      };
      session: {
        threadIdPlaceholder: string;
        loadButton: string;
        exportButton: string;
        loadRequired: string;
        exportSuccess: string;
        emptyState: string;
        loading: string;
        noFacts: string;
        factCount: string;
        categoryLabel: string;
        confidenceLabel: string;
        createdLabel: string;
        correctionLabel: string;
      };
      markdown: {
        overview: string;
        userContext: string;
        work: string;
        personal: string;
        topOfMind: string;
        historyBackground: string;
        recentMonths: string;
        earlierContext: string;
        longTermBackground: string;
        updatedAt: string;
        facts: string;
        empty: string;
        table: {
          category: string;
          confidence: string;
          confidenceLevel: {
            veryHigh: string;
            high: string;
            normal: string;
            unknown: string;
          };
          content: string;
          source: string;
          createdAt: string;
          view: string;
        };
      };
    };
    appearance: {
      themeTitle: string;
      themeDescription: string;
      system: string;
      light: string;
      dark: string;
      industrialLight: string;
      industrialDark: string;
      systemDescription: string;
      lightDescription: string;
      darkDescription: string;
      industrialLightDescription: string;
      industrialDarkDescription: string;
      languageTitle: string;
      languageDescription: string;
    };
    tools: {
      title: string;
      description: string;
      tabs: {
        toolManagement: string;
        capabilities: string;
        a2uiDebug: string;
      };
    };
    skills: {
      title: string;
      description: string;
      createSkill: string;
      emptyTitle: string;
      emptyDescription: string;
      emptyButton: string;
    };
    notification: {
      title: string;
      description: string;
      requestPermission: string;
      deniedHint: string;
      testButton: string;
      testTitle: string;
      testBody: string;
      notSupported: string;
      disableNotification: string;
    };
    account: {
      profileTitle: string;
      email: string;
      realName: string;
      userName: string;
      role: string;
      signOut: string;
    };
    acknowledge: {
      emptyTitle: string;
      emptyDescription: string;
    };
  };

  // Admin
  admin: {
    title: string;
    dashboard: string;
    tenants: string;
    usage: string;
    totalTenants: string;
    activeToday: string;
    llmCallsToday: string;
    tokensToday: string;
    costToday: string;
    costThisMonth: string;
    totalThreads: string;
    costTrend: string;
    tokenUsage: string;
    createTenant: string;
    tenantId: string;
    tenantIdPlaceholder: string;
    displayName: string;
    displayNamePlaceholder: string;
    create: string;
    users: string;
    threads: string;
    active: string;
    inactive: string;
    usageReports: string;
    startDate: string;
    endDate: string;
    filter: string;
    totalRecords: string;
    totalCost: string;
    totalTokens: string;
    records: string;
    timestamp: string;
    tenant: string;
    user: string;
    actor: string;
    model: string;
    input: string;
    output: string;
    total: string;
    cost: string;
    noUsageRecords: string;
    error: string;
    logs: string;
    auditLogs: string;
    currentTenant: string;
    currentScope: string;
    globalScope: string;
    tenantScope: string;
    globalScopeView: string;
    tenantScopedView: string;
    tenantManagementRestricted: string;
    direction: string;
    all: string;
    input_dir: string;
    output_dir: string;
    blocked: string;
    allowed_status: string;
    noLogRecords: string;
    previous: string;
    next: string;
    page: string;
    dailyQuota: string;
    monthlyQuota: string;
    delete: string;
    save: string;
    edit: string;
    confirmDelete: string;
    confirmDeleteDesc: string;
    cancel: string;
    manageUsers: string;
    tenantUsers: string;
    removeUser: string;
    noTenantUsers: string;
    tenantUserRemoveConfirm: string;
    tenantDisabledTitle: string;
    tenantDisabledDesc: string;
    tenantNotFoundTitle: string;
    tenantNotFoundDesc: string;
  };

  // Template Marketplace
  marketplace: {
    title: string;
    subtitle: string;
    searchPlaceholder: string;
    allCategories: string;
    sortByNewest: string;
    sortByRating: string;
    sortByInstalls: string;
    noTemplates: string;
    loading: string;
    install: string;
    installTo: string;
    installPrivate: string;
    installTenant: string;
    installNamePlaceholder: string;
    installSuccess: string;
    installFailed: string;
    reviews: string;
    writeReview: string;
    rating: string;
    comment: string;
    commentPlaceholder: string;
    submitReview: string;
    reviewSuccess: string;
    reviewFailed: string;
    noReviews: string;
    beFirst: string;
    description: string;
    noDescription: string;
    tags: string;
    published: string;
    version: string;
    visibility: string;
    featured: string;
    category: string;
    sortBy: string;
    industrialIntelligence: string;
    industrialSubtitle: string;
    noIndustrialTemplates: string;
    browseAllTemplates: string;
    loadingIndustrial: string;
    // Report templates page
    pageTitle: string;
    pageDescription: string;
    visibilityPrivate: string;
    visibilityTenant: string;
    visibilityBuiltin: string;
    statusDraft: string;
    statusPublished: string;
    statusArchived: string;
    createTemplate: string;
    templateMarketplace: string;
    loadingFailed: string;
    emptyMyTemplates: string;
    emptyNoTemplates: string;
    updatedAt: string;
  };

  reportTemplates: {
    backToTemplates: string;
    notFound: string;
    installedFromMarketplace: string;
    updateAvailable: string;
    validateDsl: string;
    saveDraft: string;
    publishNewVersion: string;
    archive: string;
    archiveSuccess: string;
    archiveFailed: string;
    deleteSuccess: string;
    deleteFailed: string;
    versions: string;
    workingDraft: string;
    jsonParseFailed: string;
    publishedReadonly: string;
    builtinReadonly: string;
    dslJson: string;
    dslYaml: string;
    deleteTemplateTitle: string;
    deleteTemplateDescription: string;
    deletePermanently: string;
    deleting: string;
  };

  // Template Editor
  editor: {
    title: string;
    unsavedChanges: string;
    allSaved: string;
    save: string;
    saving: string;
    publish: string;
    publishing: string;
    export: string;
    marketplace: string;
    preview: string;
    yaml: string;
    formSteps: string;
    dataSteps: string;
    sections: string;
    properties: string;
    validation: string;
    validating: string;
    validationSuccess: string;
    validationFailed: string;
    saveSuccess: string;
    saveFailed: string;
    publishSuccess: string;
    publishFailed: string;
    publishToMarketplace: string;
    publishSuccessMsg: string;
    publishFailedMsg: string;
    exportSuccess: string;
    exportFailed: string;
    createFromBlueprint: string;
    chooseBlueprint: string;
    noBlueprints: string;
    loadingBlueprints: string;
    useBlueprint: string;
    createFrom: string;
    blueprintTemplateNameLabel: string;
    blueprintTemplateNamePlaceholder: string;
    blueprintTemplateNameHint: string;
    templateCreated: string;
    createFailed: string;
    marketplaceSource: string;
    updateAvailable: string;
    templateEditorFallbackTitle: string;
    publishToMarketplaceDescription: string;
    exportTemplateTitle: string;
    exportTemplateDescription: string;
    downloadTemplatePackage: string;
    displayNameRequired: string;
    displayNameLabel: string;
    descriptionLabel: string;
    visibilityLabel: string;
    categoryLabel: string;
    tagsLabel: string;
    tagsHint: string;
    templateNameLabel: string;
    templateNamePlaceholder: string;
    templateNameHint: string;
    templateDisplayNameLabel: string;
    templateDisplayNamePlaceholder: string;
    templateDescriptionPlaceholder: string;
    structure: string;
    transforms: string;
    exportFormats: string;
    exportFormatsPlaceholder: string;
    exportFormatsHint: string;
    components: string;
    formFieldsGroup: string;
    sectionComponentsGroup: string;
    dataPipelineGroup: string;
    markdown: string;
    textInput: string;
    selectInput: string;
    multiSelectInput: string;
    datePicker: string;
    deviceSelector: string;
    deviceMultiSelect: string;
    card: string;
    cardGroup: string;
    table: string;
    chart: string;
    image: string;
    dataStep: string;
    transform: string;
    optionOne: string;
    optionTwo: string;
    noFormSteps: string;
    dropToCreateStep: string;
    addFirstStep: string;
    addStep: string;
    stepDefaultTitle: string;
    fields: string;
    noDataSteps: string;
    addDataStep: string;
    script: string;
    argsJson: string;
    scriptPlaceholder: string;
    argsPlaceholder: string;
    noTransforms: string;
    addTransform: string;
    transformScriptPlaceholder: string;
    inputSource: string;
    transformInputPlaceholder: string;
    noSections: string;
    addSection: string;
    newSection: string;
    sectionTitlePlaceholder: string;
    sectionSourcePlaceholder: string;
    dslValid: string;
    errorCountLabel: string;
    warningCountLabel: string;
    yamlSource: string;
    lineCountLabel: string;
  };

  // Onboarding
  onboarding: {
    welcome: {
      title: string;
      description: string;
    };
    selectDevice: {
      title: string;
      description: string;
      sampleDevices: { id: string; name: string; type: string }[];
    };
    quickAnalysis: {
      title: string;
      description: string;
      runAnalysis: string;
      analyzing: string;
    };
    viewReport: {
      title: string;
      description: string;
      viewReport: string;
    };
    finish: {
      title: string;
      description: string;
      startUsing: string;
    };
    skip: string;
    next: string;
    back: string;
  };

  // Report Runs
  reportRuns: {
    pageTitle: string;
    pageDescription: string;
    statusPending: string;
    statusRunning: string;
    statusSuccess: string;
    statusFailed: string;
    statusCancelled: string;
    loading: string;
    loadingFailed: string;
    emptyRuns: string;
    emptyChats: string;
    headerRunId: string;
    headerTemplate: string;
    headerVersion: string;
    headerStatus: string;
    headerCreatedAt: string;
    headerParams: string;
    headerSourceChat: string;
    tabRuns: string;
    tabChats: string;
    titlePrefix: string;
    createTicket: string;
    linkTicket: string;
    runFailed: string;
    templateUnavailable: string;
    knowledgeSourceUnavailable: string;
    runInterrupted: string;
    dataStepFailed: string;
    detailBreadcrumb: string;
    backToHistory: string;
    backToSourceChat: string;
    notFound: string;
    detailTemplateLabel: string;
    detailStatusLabel: string;
    detailCreatedLabel: string;
    downloadMarkdown: string;
    downloadPdf: string;
    pdfUnavailable: string;
    lineage: string;
    lineageTemplatePrefix: string;
    lineageMarketplace: string;
    lineageRunPrefix: string;
    knowledgeSources: string;
    knowledgeSourcePrefix: string;
    unknownSource: string;
    selectedKnowledgeBases: string;
    sourceChat: string;
    openSourceConversation: string;
    noSourceContext: string;
    parameters: string;
    downloadRawParameters: string;
    dataFiles: string;
    reportPreview: string;
    previewSectionsMissing: string;
    previewPayloadMissing: string;
    rawPayload: string;
    payloadLoading: string;
  };

  // GenUI Components
  genui: {
    // Device types
    deviceTypeRotating: string;
    deviceTypePump: string;
    deviceTypeStatic: string;
    deviceTypeReciprocating: string;
    // Device selectors
    ariaDeviceSelector: string;
    ariaDeviceMultiSelector: string;
    ariaSubDeviceSelector: string;
    loadingOrgTree: string;
    loadingSubDevices: string;
    loadingFailed: string;
    retry: string;
    selectOrgNode: string;
    noDevicesUnderNode: string;
    noSubDevices: string;
    selectAll: string;
    selected: string;
    confirmSelection: string;
    submitting: string;
    subDeviceList: string;
    // Form block
    searchPlaceholder: string;
    selectAllOptions: string;
    deselectAll: string;
    noData: string;
    selectedCount: string;
    submit: string;
    skip: string;
    // Markdown block
    saveSuccess: string;
    discardUnsaved: string;
    edit: string;
    save: string;
    // Metric block
    ariaDeviation: string;
    ariaSetpoint: string;
    ariaLowLowLimit: string;
    ariaLowLimit: string;
    ariaHighLimit: string;
    ariaHighHighLimit: string;
    // Status block
    statusRunning: string;
    statusStopped: string;
    statusMaintenance: string;
    statusStandby: string;
    statusFault: string;
    statusCommLoss: string;
    // Alarm block
    alarmCritical: string;
    alarmHigh: string;
    alarmMedium: string;
    alarmLow: string;
    alarmJournal: string;
    noAlarms: string;
    acknowledged: string;
    alarmLevel: string;
    // Org tree panel
    searchOrgPlaceholder: string;
    noMatches: string;
    noOrgData: string;
  };
}
