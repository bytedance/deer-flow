import {
  CompassIcon,
  GraduationCapIcon,
  ImageIcon,
  MicroscopeIcon,
  PenLineIcon,
  ShapesIcon,
  SparklesIcon,
  VideoIcon,
} from "lucide-react";

import type { Translations } from "./types";

export const viVN: Translations = {
  // Locale meta
  locale: {
    localName: "Tiếng Việt",
  },

  // Common
  common: {
    home: "Trang chủ",
    settings: "Cài đặt",
    delete: "Xóa",
    edit: "Chỉnh sửa",
    rename: "Đổi tên",
    share: "Chia sẻ",
    openInNewWindow: "Mở trong cửa sổ mới",
    close: "Đóng",
    more: "Thêm",
    search: "Tìm kiếm",
    loadMore: "Tải thêm",
    download: "Tải xuống",
    thinking: "Đang suy nghĩ",
    artifacts: "Artifacts",
    public: "Công khai",
    custom: "Tùy chỉnh",
    notAvailableInDemoMode: "Không khả dụng ở chế độ Demo",
    loading: "Đang tải...",
    version: "Phiên bản",
    lastUpdated: "Cập nhật lần cuối",
    code: "Mã",
    preview: "Xem trước",
    cancel: "Hủy",
    save: "Lưu",
    install: "Cài đặt",
    create: "Tạo",
    import: "Nhập",
    export: "Xuất",
    exportAsMarkdown: "Xuất dưới dạng Markdown",
    exportAsJSON: "Xuất dưới dạng JSON",
    exportSuccess: "Đã xuất cuộc hội thoại",
    regenerate: "Tạo lại",
    branch: "Nhánh cuộc hội thoại",
    showArtifacts: "Hiển thị artifact của cuộc hội thoại này",
  },

  // Home
  home: {
    docs: "Tài liệu",
    blog: "Blog",
  },

  // Welcome
  welcome: {
    greeting: "Xin chào!",
    description:
      "Chào mừng bạn đến với 🦌 DeerFlow, một siêu tác nhân mã nguồn mở. Với các kỹ năng tích hợp sẵn và tùy chỉnh, DeerFlow giúp bạn tìm kiếm trên web, phân tích dữ liệu và tạo ra các thành phần như slide, trang web và làm hầu hết mọi thứ.",

    createYourOwnSkill: "Tạo Kỹ Năng Của Riêng Bạn",
    createYourOwnSkillDescription:
      "Tạo kỹ năng của riêng bạn để giải phóng sức mạnh của DeerFlow. Với các kỹ năng tùy chỉnh, DeerFlow có thể giúp bạn tìm kiếm trên web, phân tích dữ liệu, tạo ra các slide, trang web và làm hầu hết mọi thứ.",
  },

  // Clipboard
  clipboard: {
    copyToClipboard: "Sao chép vào bộ nhớ tạm",
    copiedToClipboard: "Đã sao chép vào bộ nhớ tạm",
    failedToCopyToClipboard: "Sao chép vào bộ nhớ tạm thất bại",
    linkCopied: "Đã sao chép liên kết vào bộ nhớ tạm",
  },

  // Citations
  citations: {
    sourcesSummary: (count) =>
      `Đã sử dụng ${count} ${count === 1 ? "nguồn" : "nguồn"}`,
    citeCount: (count) => `${count} trích dẫn`,
    copyReference: (title) => `Sao chép trích dẫn ${title}`,
    copiedReference: (title) => `Đã sao chép trích dẫn ${title}`,
  },

  // Workspace Changes
  workspaceChanges: {
    title: "Thay đổi trong không gian làm việc",
    editedTitle: (count) => `Đã sửa ${count} ${count === 1 ? "tệp" : "tệp"}`,
    badge: (count, additions, deletions) =>
      `${count} ${count === 1 ? "tệp" : "tệp"} thay đổi +${additions} -${deletions}`,
    viewChanges: "Xem thay đổi",
    created: "Đã tạo",
    modified: "Đã sửa",
    deleted: "Đã xóa",
    openFile: "Mở tệp",
    loading: "Đang tải các thay đổi...",
    noChanges: "Không có thay đổi nào được ghi lại.",
    diffUnavailable: "Không có diff",
    binaryUnavailable: "Tệp nhị phân. Không có diff.",
    largeUnavailable: "Tệp quá lớn. Bỏ qua diff.",
    sensitiveUnavailable: "Đường dẫn nhạy cảm. Nội dung bị ẩn.",
    truncatedUnavailable: "Bỏ qua diff vì tập hợp thay đổi quá lớn.",
    truncatedSummary: "Một số thay đổi đã bị cắt bớt.",
  },

  // Input Box
  inputBox: {
    placeholder: "Tôi có thể giúp gì cho bạn hôm nay?",
    createSkillPrompt:
      "Chúng ta sẽ cùng xây dựng một kỹ năng mới từng bước với `skill-creator`. Đầu tiên, bạn muốn kỹ năng này làm gì?",
    addAttachments: "Thêm tệp đính kèm",
    inputPolish: "Làm mượt câu lệnh",
    inputPolishing: "Đang làm mượt câu lệnh...",
    inputPolishNoChanges: "Câu lệnh này đã đủ rõ ràng.",
    inputPolishFailed: "Làm mượt câu lệnh thất bại.",
    inputPolishUndo: "Hoàn tác",
    inputPolishCancel: "Hủy làm mượt",
    mode: "Chế độ",
    flashMode: "Flash",
    flashModeDescription: "Nhanh và hiệu quả, nhưng có thể kém chính xác hơn",
    reasoningMode: "Reasoning",
    reasoningModeDescription:
      "Suy luận trước khi hành động, cân bằng giữa thời gian và độ chính xác",
    proMode: "Pro",
    proModeDescription:
      "Suy luận, lập kế hoạch và thực thi, cho kết quả chính xác hơn, có thể mất nhiều thời gian hơn",
    ultraMode: "Ultra",
    ultraModeDescription:
      "Chế độ Pro kết hợp các tác nhân phụ để chia sẻ công việc; tốt nhất cho các tác vụ phức tạp nhiều bước",
    reasoningEffort: "Nỗ lực suy luận",
    reasoningEffortMinimal: "Tối thiểu",
    reasoningEffortMinimalDescription: "Truy xuất + Đầu ra trực tiếp",
    reasoningEffortLow: "Thấp",
    reasoningEffortLowDescription: "Kiểm tra logic đơn giản + Suy luận nông",
    reasoningEffortMedium: "Trung bình",
    reasoningEffortMediumDescription:
      "Phân tích logic đa lớp + Xác minh cơ bản",
    reasoningEffortHigh: "Cao",
    reasoningEffortHighDescription:
      "Suy luận logic toàn diện + Xác minh đa hướng + Kiểm tra ngược",
    searchModels: "Tìm kiếm mô hình...",
    surpriseMe: "Bất ngờ",
    surpriseMePrompt: "Làm tôi bất ngờ",
    followupLoading: "Đang tạo câu hỏi tiếp theo...",
    followupConfirmTitle: "Gửi gợi ý?",
    followupConfirmDescription:
      "Bạn đã có văn bản trong ô nhập liệu. Chọn cách gửi.",
    followupConfirmAppend: "Thêm vào cuối & gửi",
    followupConfirmReplace: "Thay thế & gửi",
    suggestionPlaceholderRequired:
      "Thay thế các chỗ trống gợi ý trước khi gửi.",
    goalCommandDescription: "Đặt, hiển thị hoặc xóa mục tiêu hoạt động",
    compactCommandDescription:
      "Nén ngữ cảnh cũ hơn trong khi vẫn giữ hiển thị cuộc trò chuyện",
    goalLabel: "Goal",
    goalContinuing: "Đang tiếp tục {count}/{max}",
    goalContinuationTooltip:
      "Tự động tiếp tục {count}/{max} lần hướng tới mục tiêu; dừng khi đạt giới hạn.",
    goalSet: "Đã đặt mục tiêu.",
    goalCleared: "Đã xóa mục tiêu.",
    goalNone: "Không có mục tiêu hoạt động.",
    goalActive: "Mục tiêu hoạt động: {goal}",
    goalFailed: "Lệnh mục tiêu thất bại.",
    compactSuccess:
      "Đã nén ngữ cảnh cũ hơn. Cuộc trò chuyện đầy đủ vẫn hiển thị; các lượt gọi mô hình tiếp theo sẽ sử dụng tóm tắt và tin nhắn gần đây.",
    compactSkipped: "Ngữ cảnh hiện tại chưa cần nén.",
    compactFailed: "Nén ngữ cảnh thất bại.",
    suggestions: [
      {
        suggestion: "Viết",
        prompt: "Viết một bài blog về xu hướng mới nhất về [topic]",
        icon: PenLineIcon,
      },
      {
        suggestion: "Nghiên cứu",
        prompt:
          "Tiến hành nghiên cứu chuyên sâu về [topic] và tóm tắt kết quả.",
        icon: MicroscopeIcon,
      },
      {
        suggestion: "Thu thập",
        prompt: "Thu thập dữ liệu từ [source] và tạo báo cáo.",
        icon: ShapesIcon,
      },
      {
        suggestion: "Học tập",
        prompt: "Tìm hiểu về [topic] và tạo tài liệu hướng dẫn.",
        icon: GraduationCapIcon,
      },
    ],
    suggestionsCreate: [
      {
        suggestion: "Trang web",
        prompt: "Tạo một trang web về [topic]",
        icon: CompassIcon,
      },
      {
        suggestion: "Hình ảnh",
        prompt: "Tạo một hình ảnh về [topic]",
        icon: ImageIcon,
      },
      {
        suggestion: "Video",
        prompt: "Tạo một video về [topic]",
        icon: VideoIcon,
      },
      {
        type: "separator",
      },
      {
        suggestion: "Kỹ năng",
        prompt:
          "Chúng ta sẽ cùng xây dựng một kỹ năng mới từng bước với `skill-creator`. Đầu tiên, bạn muốn kỹ năng này làm gì?",
        icon: SparklesIcon,
      },
    ],
    pleaseWaitStreaming: "Vui lòng đợi phản hồi hiện tại hoàn thành.",
  },

  // Sidebar
  sidebar: {
    newChat: "Trò chuyện mới",
    chats: "Trò chuyện",
    channels: "Kênh kết nối",
    recentChats: "Gần đây",
    demoChats: "Cuộc trò chuyện Demo",
    agents: "Tác nhân",
    scheduledTasks: "Scheduled tasks",
    agentsDisabledTooltip: "Tính năng chưa được bật",
  },

  // Scheduled tasks
  scheduledTasks: {
    scheduleType: {
      cron: "Định kỳ",
      once: "Một lần",
    },
    preset: {
      label: "Lặp lại",
      hourly: "Hàng giờ",
      daily: "Hàng ngày",
      weekly: "Hàng tuần",
      monthly: "Hàng tháng",
      custom: "Tùy chỉnh cron",
    },
    fields: {
      minute: "Phút",
      time: "Thời gian",
      weekday: "Vào",
      dayOfMonth: "Ngày trong tháng",
      cron: "Biểu thức cron",
      cronPlaceholder: "0 9 * * *",
      runAt: "Chạy lúc",
      timezone: "Múi giờ",
    },
    weekdays: {
      mon: "T2",
      tue: "T3",
      wed: "T4",
      thu: "T5",
      fri: "T6",
      sat: "T7",
      sun: "CN",
    },
    preview: "Xem trước",
    cronHelp: "Mở crontab.guru",
    create: {
      title: "Tạo tác vụ định kỳ",
      taskTitle: "Tiêu đề tác vụ",
      prompt: "Câu lệnh (Prompt)",
      submit: "Tạo mới",
      fillRequired: "Vui lòng điền đầy đủ thông tin bắt buộc",
    },
    context: {
      fresh: "Luồng mới",
      reuse: "Tái sử dụng luồng",
      threadIdPlaceholder: "ID luồng (Thread ID)",
    },
    filters: {
      allStatuses: "Tất cả trạng thái",
      enabled: "Đã bật",
      paused: "Tạm dừng",
      completed: "Đã hoàn thành",
      failed: "Thất bại",
      allTypes: "Tất cả các loại",
      cron: "Định kỳ (Cron)",
      once: "Một lần",
    },
    detail: {
      contextMode: "Chế độ ngữ cảnh",
      thread: "Luồng",
      lastThread: "Luồng gần nhất",
      schedule: "Lịch trình",
      nextRun: "Lần chạy tiếp theo",
      lastRun: "Lần chạy gần nhất",
      lastRunId: "ID lần chạy gần nhất",
      lastError: "Lỗi gần nhất",
      runsCount: "{count} lần chạy",
      runsCountOne: "{count} lần chạy",
      noRuns: "Chưa chạy lần nào",
      noSelection: "Chưa chọn tác vụ định kỳ",
      filteredByThread: "Lọc theo luồng: {id}",
      loadFailed: "Không thể tải danh sách tác vụ định kỳ",
    },
    actions: {
      edit: "Chỉnh sửa",
      cancelEdit: "Hủy chỉnh sửa",
      pause: "Tạm dừng",
      resume: "Tiếp tục",
      trigger: "Kích hoạt ngay",
      delete: "Xóa",
    },
    deleteConfirm:
      "Bạn có chắc chắn muốn xóa tác vụ định kỳ này? Hành động này không thể hoàn tác.",
    errors: {
      create: "Tạo tác vụ định kỳ thất bại",
      update: "Cập nhật tác vụ định kỳ thất bại",
      pause: "Tạm dừng tác vụ định kỳ thất bại",
      resume: "Tiếp tục tác vụ định kỳ thất bại",
      trigger: "Kích hoạt tác vụ định kỳ thất bại",
      delete: "Xóa tác vụ định kỳ thất bại",
    },
    edit: {
      titlePlaceholder: "Chỉnh sửa tiêu đề",
      promptPlaceholder: "Chỉnh sửa câu lệnh",
      submit: "Lưu thay đổi",
    },
    status: {
      enabled: "Đã bật",
      paused: "Tạm dừng",
      running: "Đang chạy",
      completed: "Đã hoàn thành",
      failed: "Thất bại",
      cancelled: "Đã hủy",
    },
    runTrigger: { scheduled: "tự động", manual: "thủ công" },
    runStatus: {
      queued: "Đang chờ",
      running: "Đang chạy",
      success: "Thành công",
      failed: "Thất bại",
      skipped: "Bỏ qua",
      interrupted: "Bị gián đoạn",
    },
    recipes: {
      label: "Tạo nhanh",
      trending: {
        title: "GitHub Trending hàng ngày",
        desc: "Tóm tắt top 10 kho lưu trữ thịnh hành hôm nay",
      },
      news: {
        title: "Tin tức công nghệ hàng ngày",
        desc: "Thu thập và tóm tắt tin tức công nghệ hàng đầu trong ngày",
      },
      issues: {
        title: "Phân loại Issue trên GitHub",
        desc: "Phân loại các issue đang mở của một kho lưu trữ (điền {{repo}})",
      },
      weekly: {
        title: "Báo cáo tuần",
        desc: "Tổng hợp tóm tắt tuần vào mỗi thứ Hai",
      },
    },
  },

  // Agents
  agents: {
    title: "Tác nhân (Agents)",
    description:
      "Tạo và quản lý các tác nhân tùy chỉnh với các chỉ dẫn và năng lực chuyên biệt.",
    newAgent: "Tác nhân mới",
    emptyTitle: "Chưa có tác nhân tùy chỉnh nào",
    emptyDescription:
      "Tạo tác nhân tùy chỉnh đầu tiên của bạn với các chỉ dẫn hệ thống chuyên biệt.",
    featureDisabledTitle: "Tính năng Tác nhân chưa được bật",
    featureDisabledDescription:
      "Tính năng này chưa được kích hoạt trên máy chủ này. Vui lòng liên hệ với quản trị viên.",
    chat: "Trò chuyện",
    delete: "Xóa",
    deleteConfirm:
      "Bạn có chắc chắn muốn xóa tác nhân này? Hành động này không thể hoàn tác.",
    deleteSuccess: "Đã xóa tác nhân",
    newChat: "Trò chuyện mới",
    createPageTitle: "Thiết kế Tác nhân của bạn",
    createPageSubtitle:
      "Mô tả tác nhân bạn muốn — tôi sẽ giúp bạn tạo tác nhân đó thông qua trò chuyện.",
    nameStepTitle: "Đặt tên cho Tác nhân mới",
    nameStepHint:
      "Chỉ sử dụng chữ cái, chữ số và dấu gạch ngang — được lưu dưới dạng viết thường (ví dụ: code-reviewer)",
    nameStepPlaceholder: "ví dụ: code-reviewer",
    nameStepContinue: "Tiếp tục",
    nameStepInvalidError:
      "Tên không hợp lệ — chỉ sử dụng chữ cái, chữ số và dấu gạch ngang",
    nameStepAlreadyExistsError: "Tác nhân với tên này đã tồn tại",
    nameStepNetworkError:
      "Yêu cầu mạng thất bại — kiểm tra kết nối mạng hoặc máy chủ của bạn",
    nameStepCheckError:
      "Không thể kiểm tra tính khả dụng của tên — vui lòng thử lại",
    nameStepCheckErrorWithDetail: "Kiểm tra tên thất bại: {detail}",
    nameStepApiDisabledError:
      "Quản lý tác nhân tùy chỉnh chưa được bật trên máy chủ này. Vui lòng liên hệ với quản trị viên.",
    nameStepBootstrapMessage:
      "Tên tác nhân mới là {name}. Giúp tôi thiết kế mục đích, hành vi và SOUL.md của nó trước khi lưu.",
    save: "Lưu tác nhân",
    saving: "Đang lưu tác nhân...",
    saveRequested:
      "Đã yêu cầu lưu. DeerFlow đang tạo và lưu phiên bản ban đầu.",
    saveHint:
      "Bạn có thể lưu tác nhân này bất kỳ lúc nào từ menu trên cùng bên phải, ngay cả khi đây chỉ là bản nháp đầu tiên.",
    saveCommandMessage:
      "Vui lòng lưu tác nhân tùy chỉnh này ngay dựa trên tất cả các thảo luận của chúng ta. Coi đây là xác nhận rõ ràng của tôi để lưu. Nếu một số chi tiết vẫn còn thiếu, hãy đưa ra giả định hợp lý, tạo tóm tắt SOUL.md bằng tiếng Anh và gọi setup_agent ngay lập tức mà không cần hỏi thêm xác nhận từ tôi.",
    agentCreatedPendingRefresh:
      "Tác nhân đã được tạo, nhưng DeerFlow chưa thể tải nó. Vui lòng tải lại trang sau giây lát.",
    more: "Hành động khác",
    agentCreated: "Đã tạo tác nhân!",
    startChatting: "Bắt đầu trò chuyện",
    backToGallery: "Quay lại Thư viện",
  },

  // Breadcrumb
  breadcrumb: {
    workspace: "Không gian làm việc",
    chats: "Trò chuyện",
  },

  // Workspace
  workspace: {
    officialWebsite: "Trang web chính thức của DeerFlow",
    githubTooltip: "DeerFlow trên GitHub",
    settingsAndMore: "Cài đặt và cấu hình khác",
    visitGithub: "DeerFlow trên GitHub",
    reportIssue: "Báo cáo sự cố",
    contactUs: "Liên hệ với chúng tôi",
    about: "Giới thiệu DeerFlow",
    logout: "Đăng xuất",
    gatewayUnavailable: "Cổng kết nối (Gateway) tạm thời không khả dụng.",
    gatewayUnavailableRetrying: "Đang thử lại trong nền...",
  },

  // Conversation
  conversation: {
    noMessages: "Chưa có tin nhắn nào",
    startConversation: "Bắt đầu cuộc hội thoại để xem tin nhắn tại đây",
    branchCreated: "Đã tạo nhánh cuộc hội thoại",
    branchFailed: "Tạo nhánh cuộc hội thoại thất bại.",
  },

  // Chats
  chats: {
    searchChats: "Tìm kiếm cuộc trò chuyện",
    loadMoreToSearch: "Tải thêm để tìm kiếm các cuộc trò chuyện cũ hơn",
    loadingMore: "Đang tải thêm...",
    loadOlderChats: "Tải các cuộc trò chuyện cũ hơn",
  },

  // Sidecar
  sidecar: {
    title: "Trò chuyện phụ",
    open: "Mở trò chuyện phụ",
    close: "Đóng trò chuyện phụ",
    delete: "Xóa trò chuyện phụ",
    deleteConfirm:
      "Bạn có chắc chắn muốn xóa cuộc trò chuyện phụ này? Hành động này không thể hoàn tác. Để ẩn cuộc trò chuyện, sử dụng nút chuyển đổi trò chuyện phụ trên thanh tiêu đề.",
    deleteSuccess: "Đã xóa trò chuyện phụ",
    deleteFailed: "Xóa trò chuyện phụ thất bại.",
    addToConversation: "Thêm vào cuộc hội thoại",
    askInSideChat: "Hỏi trong trò chuyện phụ",
    reference: "Tham chiếu",
    selectedTextFragment: "{count} đoạn văn bản đã chọn",
    selectedTextFragments: "{count} đoạn văn bản đã chọn",
    clearReferences: "Xóa các tham chiếu đã chọn",
    emptyTitle: "Đặt câu hỏi tiếp theo",
    emptyDescription: "Đặt câu hỏi tiếp theo dựa trên văn bản được tham chiếu.",
    placeholder: "Hỏi sâu hơn...",
    send: "Gửi",
    sendFailed: "Gửi tin nhắn trò chuyện phụ thất bại.",
    noContext: "Chưa chọn ngữ cảnh",
    continuing: "Tiếp tục trong cuộc trò chuyện phụ này",
    selectionCrossesMessages:
      "Lựa chọn kéo dài qua nhiều tin nhắn. Chọn văn bản trong một phản hồi duy nhất để trích dẫn.",
  },

  // Channels
  channels: {
    title: "Kênh kết nối",
    connect: "Kết nối",
    modify: "Sửa đổi",
    reconnect: "Kết nối lại",
    disconnect: "Ngắt kết nối",
    connected: "Đã kết nối",
    notConnected: "Chưa kết nối",
    pending: "Đang chờ",
    revoked: "Đã ngắt kết nối",
    disabled: "Đã vô hiệu hóa",
    unconfigured: "Chưa cấu hình",
    unavailable: "Kết nối kênh hiện đang không khả dụng.",
    unavailableShort: "Không khả dụng",
    setupTitle: (name: string) => `Kết nối ${name}`,
    setupEditTitle: (name: string) => `Sửa đổi kết nối ${name}`,
    setupDescription:
      "Nhập các giá trị cần thiết cho quy trình máy chủ này. Chúng không được ghi vào config.yaml.",
    saveAndConnect: "Lưu và kết nối",
    saveChanges: "Lưu thay đổi",
    descriptions: {
      telegram: "Tin nhắn trực tiếp Telegram qua bot DeerFlow của bạn.",
      slack: "Tin nhắn và lượt nhắc trong không gian làm việc Slack.",
      discord: "Tin nhắn máy chủ Discord qua bot DeerFlow của bạn.",
      feishu: "Tin nhắn Feishu và Lark qua ứng dụng DeerFlow của bạn.",
      dingtalk: "Tin nhắn DingTalk Stream Push qua bot DeerFlow của bạn.",
      wechat: "Tin nhắn WeChat iLink qua bot DeerFlow của bạn.",
      wecom: "Tin nhắn WeCom qua bot AI DeerFlow của bạn.",
    },
    connectedAs: (name: string) => `Đã kết nối dưới tên ${name}.`,
  },

  // Page titles (document title)
  pages: {
    appName: "DeerFlow",
    chats: "Cuộc trò chuyện",
    newChat: "Trò chuyện mới",
    untitled: "Chưa đặt tên",
  },

  // Tool calls
  toolCalls: {
    moreSteps: (count: number) => `Thêm ${count} bước nữa`,
    lessSteps: "Thu gọn",
    executeCommand: "Thực thi lệnh",
    presentFiles: "Trình bày tệp",
    needYourHelp: "Cần sự trợ giúp của bạn",
    useTool: (toolName: string) => `Sử dụng công cụ "${toolName}"`,
    searchFor: (query: string) => `Tìm kiếm "${query}"`,
    searchForRelatedInfo: "Tìm kiếm thông tin liên quan",
    searchForRelatedImages: "Tìm kiếm hình ảnh liên quan",
    searchForRelatedImagesFor: (query: string) =>
      `Tìm kiếm hình ảnh liên quan cho "${query}"`,
    searchOnWebFor: (query: string) => `Tìm kiếm trên web cho "${query}"`,
    viewWebPage: "Xem trang web",
    listFolder: "Liệt kê thư mục",
    readFile: "Đọc tệp",
    writeFile: "Ghi tệp",
    clickToViewContent: "Nhấp để xem nội dung tệp",
    writeTodos: "Cập nhật danh sách việc cần làm",
    skillInstallTooltip: "Cài đặt kỹ năng và cung cấp cho DeerFlow",
  },

  humanInput: {
    answered: "Đã trả lời",
    pending: "Đang gửi...",
    readOnly: "Chỉ đọc",
    otherLabel: "Câu trả lời khác",
    otherPlaceholder: "Nhập câu trả lời khác...",
    submit: "Gửi",
    emptyError: "Nhập câu trả lời trước khi gửi.",
    answeredValue: (value: string) => `Đã trả lời: ${value}`,
  },

  // Subtasks
  uploads: {
    uploading: "Đang tải lên...",
    uploadingFiles: "Đang tải lên các tệp, vui lòng đợi...",
    limitsHint: (maxFiles: number, maxFileSize: string, maxTotalSize: string) =>
      `Thêm tệp đính kèm (tối đa ${maxFiles} tệp, mỗi tệp tối đa ${maxFileSize}, tổng cộng tối đa ${maxTotalSize}). Hầu hết các loại tệp thông dụng đều được hỗ trợ; nén các gói .app của macOS trước.`,
    filesTooLarge: (files: string, maxFileSize: string) =>
      `Các tệp vượt quá giới hạn ${maxFileSize} không được thêm: ${files}.`,
    tooManyFiles: (count: number, maxFiles: number) =>
      `Không thể thêm ${count} tệp. Bạn có thể đính kèm tối đa ${maxFiles} tệp cùng lúc.`,
    totalSizeTooLarge: (count: number, maxTotalSize: string) =>
      `Không thể thêm ${count} tệp. Các tệp đính kèm có thể có tổng dung lượng tối đa là ${maxTotalSize}.`,
  },

  subtasks: {
    subtask: "Tác vụ phụ",
    executing: (count: number) =>
      `Đang thực thi ${count === 1 ? "" : count + " "}tác vụ phụ song song`,
    in_progress: "Đang chạy tác vụ phụ",
    completed: "Đã hoàn thành tác vụ phụ",
    failed: "Tác vụ phụ thất bại",
  },

  // Token Usage
  tokenUsage: {
    title: "Sử dụng Token",
    label: "Token",
    input: "Đầu vào (Input)",
    output: "Đầu ra (Output)",
    total: "Tổng số",
    view: "Hiển thị",
    unavailable:
      "Chưa có thông tin sử dụng token. Thông tin này chỉ xuất hiện sau khi mô hình phản hồi thành công và trả về dữ liệu sử dụng.",
    unavailableShort: "Không có dữ liệu trả về",
    note: "Tổng số trên thanh tiêu đề sử dụng dữ liệu tích lũy của luồng trò chuyện, cộng với lượng sử dụng hiện tại trong khi kết quả đang được truyền phát. Lượng sử dụng theo từng lượt và debug lấy từ các tin nhắn hiện đang hiển thị. Tổng số có thể khác so với trang thanh toán của nhà cung cấp dịch vụ.",
    presets: {
      off: "Tắt",
      summary: "Tóm tắt",
      perTurn: "Theo lượt",
      debug: "Gỡ lỗi (Debug)",
    },
    presetDescriptions: {
      off: "Ẩn lượng sử dụng token trên thanh tiêu đề và cuộc trò chuyện.",
      summary:
        "Chỉ hiển thị tổng số của cuộc trò chuyện hiện tại trên thanh tiêu đề.",
      perTurn:
        "Hiển thị tổng số trên thanh tiêu đề và một tóm tắt token cho mỗi lượt trợ lý.",
      debug:
        "Hiển thị tổng số trên thanh tiêu đề và chi tiết gỡ lỗi token ở cấp độ bước chạy.",
    },
    finalAnswer: "Câu trả lời cuối cùng",
    stepTotal: "Tổng số bước",
    sharedAttribution: "Được chia sẻ trên nhiều hành động trong bước này",
    subagent: (description: string) => `Tác nhân phụ: ${description}`,
    startTodo: (content: string) => `Bắt đầu việc cần làm: ${content}`,
    completeTodo: (content: string) => `Hoàn thành việc cần làm: ${content}`,
    updateTodo: (content: string) => `Cập nhật việc cần làm: ${content}`,
    removeTodo: (content: string) => `Xóa việc cần làm: ${content}`,
  },

  // Shortcuts
  shortcuts: {
    searchActions: "Tìm kiếm hành động...",
    noResults: "Không tìm thấy kết quả.",
    actions: "Hành động",
    keyboardShortcuts: "Phím tắt bàn phím",
    keyboardShortcutsDescription:
      "Điều hướng DeerFlow nhanh hơn với các phím tắt bàn phím.",
    openCommandPalette: "Mở bảng lệnh",
    toggleSidebar: "Ẩn/Hiện thanh bên",
  },

  // Settings
  settings: {
    title: "Cài đặt",
    description: "Điều chỉnh cách hiển thị và hành vi của DeerFlow.",
    sections: {
      account: "Tài khoản",
      appearance: "Giao diện",
      channels: "Kênh kết nối",
      memory: "Bộ nhớ",
      tools: "Công cụ",
      skills: "Kỹ năng",
      notification: "Thông báo",
      about: "Giới thiệu",
    },
    memory: {
      title: "Bộ nhớ",
      description:
        "DeerFlow tự động học hỏi từ các cuộc trò chuyện của bạn trong nền. Những bộ nhớ này giúp DeerFlow hiểu bạn hơn và mang lại trải nghiệm cá nhân hóa tốt hơn.",
      empty: "Không có dữ liệu bộ nhớ để hiển thị.",
      rawJson: "JSON thô",
      exportButton: "Xuất bộ nhớ",
      exportSuccess: "Đã xuất bộ nhớ",
      importButton: "Nhập bộ nhớ",
      importConfirmTitle: "Nhập bộ nhớ?",
      importConfirmDescription:
        "Điều này sẽ ghi đè lên bộ nhớ hiện tại của bạn bằng bản sao lưu JSON được chọn.",
      importFileLabel: "Tệp đã chọn",
      importInvalidFile:
        "Không thể đọc tệp bộ nhớ đã chọn. Vui lòng chọn một tệp xuất JSON hợp lệ.",
      importSuccess: "Đã nhập bộ nhớ",
      manualFactSource: "Thủ công",
      addFact: "Thêm thông tin",
      addFactTitle: "Thêm thông tin bộ nhớ",
      editFactTitle: "Sửa thông tin bộ nhớ",
      addFactSuccess: "Đã tạo thông tin bộ nhớ",
      editFactSuccess: "Đã cập nhật thông tin bộ nhớ",
      clearAll: "Xóa toàn bộ bộ nhớ",
      clearAllConfirmTitle: "Xóa toàn bộ bộ nhớ?",
      clearAllConfirmDescription:
        "Hành động này sẽ xóa tất cả các tóm tắt và thông tin đã lưu. Hành động này không thể hoàn tác.",
      clearAllSuccess: "Đã xóa toàn bộ bộ nhớ",
      factDeleteConfirmTitle: "Xóa thông tin này?",
      factDeleteConfirmDescription:
        "Thông tin này sẽ bị xóa khỏi bộ nhớ ngay lập tức. Hành động này không thể hoàn tác.",
      factDeleteSuccess: "Đã xóa thông tin",
      factContentLabel: "Nội dung",
      factCategoryLabel: "Danh mục",
      factConfidenceLabel: "Độ tin cậy",
      factContentPlaceholder: "Mô tả thông tin bộ nhớ bạn muốn lưu",
      factCategoryPlaceholder: "ngữ cảnh",
      factConfidenceHint: "Sử dụng một số từ 0 đến 1.",
      factSave: "Lưu thông tin",
      factValidationContent: "Nội dung thông tin không được để trống.",
      factValidationConfidence: "Độ tin cậy phải là một số từ 0 đến 1.",
      noFacts: "Chưa có thông tin nào được lưu.",
      summaryReadOnly:
        "Các phần tóm tắt hiện đang ở chế độ chỉ đọc. Hiện tại bạn có thể thêm, sửa, hoặc xóa các thông tin riêng lẻ, hoặc xóa toàn bộ bộ nhớ.",
      memoryFullyEmpty: "Chưa có bộ nhớ nào được lưu.",
      factPreviewLabel: "Thông tin cần xóa",
      searchPlaceholder: "Tìm kiếm bộ nhớ",
      filterAll: "Tất cả",
      filterFacts: "Thông tin",
      filterSummaries: "Tóm tắt",
      noMatches: "Không tìm thấy bộ nhớ phù hợp.",
      markdown: {
        overview: "Tổng quan",
        userContext: "Ngữ cảnh người dùng",
        work: "Công việc",
        personal: "Cá nhân",
        topOfMind: "Ưu tiên hàng đầu",
        historyBackground: "Lịch sử",
        recentMonths: "Những tháng gần đây",
        earlierContext: "Ngữ cảnh trước đó",
        longTermBackground: "Thông tin dài hạn",
        updatedAt: "Cập nhật lúc",
        facts: "Thông tin",
        empty: "(trống)",
        table: {
          category: "Danh mục",
          confidence: "Độ tin cậy",
          confidenceLevel: {
            veryHigh: "Rất cao",
            high: "Cao",
            normal: "Bình thường",
            unknown: "Không xác định",
          },
          content: "Nội dung",
          source: "Nguồn",
          createdAt: "Ngày tạo",
          view: "Xem",
        },
      },
    },
    appearance: {
      themeTitle: "Giao diện",
      themeDescription:
        "Chọn cách giao diện hiển thị theo thiết bị của bạn hoặc cố định.",
      system: "Hệ thống",
      light: "Sáng",
      dark: "Tối",
      systemDescription: "Tự động khớp với cài đặt của hệ điều hành.",
      lightDescription: "Bảng màu sáng với độ tương phản cao hơn cho ban ngày.",
      darkDescription: "Bảng màu tối giúp giảm mỏi mắt để tập trung.",
      languageTitle: "Ngôn ngữ",
      languageDescription: "Chuyển đổi giữa các ngôn ngữ.",
    },
    tools: {
      title: "Công cụ",
      description:
        "Quản lý cấu hình và trạng thái hoạt động của các công cụ MCP.",
      adminRequired: "Yêu cầu quyền quản trị viên để quản lý các công cụ MCP.",
      empty: "Chưa có công cụ MCP nào được cấu hình.",
    },
    channels: {
      title: "Kênh kết nối",
      description:
        "Kết nối các tài khoản ứng dụng nhắn tin để gửi tin nhắn đến DeerFlow từ bên ngoài trình duyệt.",
      disabled:
        "Kết nối kênh hiện đang không được bật trên máy chủ này. Hãy yêu cầu quản trị viên bật channel_connections.",
    },
    skills: {
      title: "Kỹ năng của Tác nhân",
      description:
        "Quản lý cấu hình và trạng thái kích hoạt các kỹ năng của tác nhân.",
      createSkill: "Tạo kỹ năng",
      emptyTitle: "Chưa có kỹ năng tác nhân nào",
      emptyDescription:
        "Đặt các thư mục kỹ năng tác nhân của bạn dưới thư mục `/skills/custom` tại thư mục gốc của DeerFlow.",
      emptyButton: "Tạo kỹ năng đầu tiên của bạn",
      adminRequired:
        "Yêu cầu quyền quản trị viên để quản lý các kỹ năng tác nhân.",
      installAdminRequired:
        "Yêu cầu quyền quản trị viên để cài đặt các kỹ năng tác nhân.",
    },
    notification: {
      title: "Thông báo",
      description:
        "DeerFlow chỉ gửi thông báo hoàn thành khi cửa sổ không hoạt động. Điều này đặc biệt hữu ích cho các tác vụ chạy lâu để bạn có thể chuyển sang công việc khác và nhận thông báo khi hoàn thành.",
      requestPermission: "Yêu cầu quyền thông báo",
      deniedHint:
        "Quyền thông báo đã bị từ chối. Bạn có thể bật nó trong cài đặt trang web của trình duyệt để nhận cảnh báo hoàn thành.",
      testButton: "Gửi thông báo thử nghiệm",
      testTitle: "DeerFlow",
      testBody: "Đây là thông báo thử nghiệm.",
      notSupported: "Trình duyệt của bạn không hỗ trợ thông báo.",
      disableNotification: "Vô hiệu hóa thông báo",
    },
    account: {
      profileTitle: "Thông tin cá nhân",
      email: "Email",
      role: "Vai trò",
      ssoProvider: "SSO",
      changePasswordTitle: "Đổi mật khẩu",
      changePasswordDescription: "Cập nhật mật khẩu tài khoản của bạn.",
      ssoPasswordDescription:
        "Mật khẩu được quản lý bởi nhà cung cấp SSO của bạn.",
      ssoPasswordMessage:
        "Tài khoản này đăng nhập bằng {provider}, do đó DeerFlow không thể quản lý hoặc thay đổi mật khẩu tại đây. Vui lòng sử dụng cài đặt tài khoản của nhà cung cấp SSO của bạn.",
      currentPassword: "Mật khẩu hiện tại",
      newPassword: "Mật khẩu mới",
      confirmNewPassword: "Xác nhận mật khẩu mới",
      passwordMismatch: "Mật khẩu mới không trùng khớp",
      passwordTooShort: "Mật khẩu phải có ít nhất 8 ký tự",
      passwordChangedSuccess: "Đổi mật khẩu thành công",
      networkError: "Lỗi mạng. Vui lòng thử lại.",
      updating: "Đang cập nhật...",
      updatePassword: "Cập nhật mật khẩu",
      signOut: "Đăng xuất",
    },
    acknowledge: {
      emptyTitle: "Lời cảm ơn",
      emptyDescription:
        "Thông tin ghi nhận và đóng góp sẽ được hiển thị ở đây.",
    },
  },
  login: {
    signInTitle: "Đăng nhập vào tài khoản của bạn",
    createAccountTitle: "Tạo tài khoản mới",
    email: "Email",
    emailPlaceholder: "you@example.com",
    password: "Mật khẩu",
    passwordPlaceholder: "•••••••",
    pleaseWait: "Vui lòng đợi...",
    signIn: "Đăng nhập",
    createAccount: "Tạo tài khoản",
    createAdminAccount: "Tạo tài khoản quản trị viên",
    adminSetupRequiredTitle: "Yêu cầu thiết lập tài khoản quản trị viên",
    adminSetupRequiredDescription:
      "DeerFlow cần một tài khoản quản trị viên trước khi các tài khoản thông thường mới có thể được tạo.",
    orContinueWith: "Hoặc tiếp tục với",
    ssoHint:
      "Nếu tài khoản của bạn sử dụng đăng nhập một lần, hãy chọn tùy chọn bên dưới.",
    continueWith: (provider: string) => `Tiếp tục với ${provider}`,
    noAccountSignUp: "Chưa có tài khoản? Đăng ký ngay",
    haveAccountSignIn: "Đã có tài khoản? Đăng nhập",
    backToHome: "← Quay lại trang chủ",
    networkError: "Lỗi mạng. Vui lòng thử lại.",
    authFailed: "Xác thực thất bại.",
    errors: {
      sso_failed:
        "Đăng nhập SSO thất bại. Vui lòng thử lại hoặc sử dụng đăng nhập email.",
      sso_cancelled: "Đăng nhập SSO đã bị hủy.",
      sso_account_exists:
        "Tài khoản với email này đã tồn tại. Vui lòng đăng nhập bằng mật khẩu của bạn hoặc liên hệ với quản trị viên.",
      sso_not_allowed:
        "Đăng nhập SSO không được phép đối với tài khoản của bạn. Liên hệ với quản trị viên của bạn.",
    },
  },
};
