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

export const ar: Translations = {
  // Locale meta
  locale: {
    localName: "العربية",
  },

  // Common
  common: {
    home: "الرئيسية",
    settings: "الإعدادات",
    delete: "حذف",
    rename: "إعادة تسمية",
    share: "مشاركة",
    openInNewWindow: "فتح في نافذة جديدة",
    close: "إغلاق",
    more: "المزيد",
    search: "بحث",
    download: "تحميل",
    thinking: "يفكر",
    artifacts: "المخرجات",
    public: "عام",
    custom: "مخصص",
    notAvailableInDemoMode: "غير متاح في الوضع التجريبي",
    loading: "جاري التحميل...",
    version: "الإصدار",
    lastUpdated: "آخر تحديث",
    code: "الكود",
    preview: "معاينة",
    cancel: "إلغاء",
    save: "حفظ",
    install: "تثبيت",
    create: "إنشاء",
  },

  // Welcome
  welcome: {
    greeting: "أهلاً بك مجدداً!",
    description:
      "مرحباً بك في 🦌 DeerFlow، المساعد الذكي مفتوح المصدر. من خلال المهارات المدمجة والمخصصة، يساعدك ديرفلو على البحث في الويب، وتحليل البيانات، وتوليد العروض التقديمية والصفحات والقيام بأي شيء تقريباً.",

    createYourOwnSkill: "أنشئ مهارتك الخاصة",
    createYourOwnSkillDescription:
      "قم بإنشاء مهارتك الخاصة لإطلاق العنان لقوة DeerFlow. باستخدام المهارات المخصصة، يمكن للنظام أن يساعدك في البحث وتحليل البيانات وتوليد أي شيء تقريباً.",
  },

  // Clipboard
  clipboard: {
    copyToClipboard: "نسخ إلى الحافظة",
    copiedToClipboard: "تم النسخ بنجاح",
    failedToCopyToClipboard: "فشل النسخ إلى الحافظة",
    linkCopied: "تم نسخ الرابط",
  },

  // Input Box
  inputBox: {
    placeholder: "كيف يمكنني مساعدتك اليوم؟",
    createSkillPrompt:
      "سنقوم ببناء مهارة جديدة خطوة بخطوة باستخدام `صانع المهارات`. للبدء، ماذا تريد أن تفعل هذه المهارة؟",
    addAttachments: "إضافة المرفقات",
    mode: "الوضع",
    flashMode: "فلاش",
    flashModeDescription: "سريع وفعال، لكن قد لا يكون دقيقاً جداً",
    reasoningMode: "التفكير",
    reasoningModeDescription:
      "التفكير قبل التنفيذ، توازن بين الوقت والدقة",
    proMode: "احترافي",
    proModeDescription:
      "تفكير وتخطيط وتنفيذ، لنتائج أكثر دقة (يستغرق وقتاً أطول)",
    ultraMode: "خارق",
    ultraModeDescription:
      "تفويض العمل لوكلاء فرعيين متكاملين؛ الأفضل للمهام المعقدة",
    reasoningEffort: "جهد التفكير",
    reasoningEffortMinimal: "أدنى",
    reasoningEffortMinimalDescription: "استرجاع + إجابة مباشرة",
    reasoningEffortLow: "منخفض",
    reasoningEffortLowDescription: "تحقق منطقي بسيط + استنتاج سطحي",
    reasoningEffortMedium: "متوسط",
    reasoningEffortMediumDescription:
      "تحليل منطقي متعدد الطبقات + تحقق أساسي",
    reasoningEffortHigh: "مرتفع",
    reasoningEffortHighDescription:
      "استنتاج منطقي كامل الأبعاد + تحقق متعدد المسارات + مراجعة عكسية",
    searchModels: "البحث عن النماذج...",
    surpriseMe: "فاجئني",
    surpriseMePrompt: "فاجئني بمعلومة",
    followupLoading: "جاري توليد الأسئلة المتابعة...",
    followupConfirmTitle: "إرسال الاقتراح؟",
    followupConfirmDescription:
      "لديك نص مسبقاً في صندوق الإدخال. اختر كيف تريد إرساله.",
    followupConfirmAppend: "إضافة وإرسال",
    followupConfirmReplace: "استبدال وإرسال",
    suggestions: [
      {
        suggestion: "كتابة",
        prompt: "اكتب مقالاً حول أحدث التوجهات في [الموضوع]",
        icon: PenLineIcon,
      },
      {
        suggestion: "بحث",
        prompt:
          "قم بإجراء بحث متعمق حول [الموضوع]، ولخص النتائج.",
        icon: MicroscopeIcon,
      },
      {
        suggestion: "جمع بيانات",
        prompt: "اجمع بيانات من [المصدر] وأنشئ تقريراً متكاملاً.",
        icon: ShapesIcon,
      },
      {
        suggestion: "تعلّم",
        prompt: "أريد أن أتعلم عن [الموضوع]، اصنع لي درساً مكثفاً.",
        icon: GraduationCapIcon,
      },
    ],
    suggestionsCreate: [
      {
        suggestion: "صفحة ويب",
        prompt: "صمم صفحة ويب حول [الموضوع]",
        icon: CompassIcon,
      },
      {
        suggestion: "صورة",
        prompt: "توليد صورة فحصنية حول [الموضوع]",
        icon: ImageIcon,
      },
      {
        suggestion: "فيديو",
        prompt: "إنشاء فيديو عن [الموضوع]",
        icon: VideoIcon,
      },
      {
        type: "separator",
      },
      {
        suggestion: "مهارة",
        prompt:
          "سنقوم ببناء مهارة جديدة خطوة بخطوة باستخدام `صانع المهارات`. للبدء، ماذا تريد أن تفعل هذه المهارة؟",
        icon: SparklesIcon,
      },
    ],
  },

  // Sidebar
  sidebar: {
    newChat: "محادثة جديدة",
    chats: "المحادثات",
    recentChats: "المحادثات الأخيرة",
    demoChats: "المحادثات التجريبية",
    agents: "تخصيص وكيل",
  },

  // Agents
  agents: {
    title: "الوكلاء المخصصون",
    description:
      "إنشاء وإدارة وكلاء مخصصين بتلقين وقدرات خاصة.",
    newAgent: "وكيل جديد",
    emptyTitle: "لا يوجد وكلاء مخصصون حتى الآن",
    emptyDescription:
      "قم بإنشاء وكيلك المخصص الأول بهوية ومهام محددة.",
    chat: "محادثة",
    delete: "حذف",
    deleteConfirm:
      "هل أنت متأكد من حذف هذا الوكيل؟ لا يمكن التراجع عن هذا الإجراء.",
    deleteSuccess: "تم حذف الوكيل",
    newChat: "محادثة جديدة",
    createPageTitle: "صمم وكيلك المخصص",
    createPageSubtitle:
      "قم بوصف الوكيل الذي تريده — سأقوم بتصميمه لك من خلال محادثة معنا.",
    nameStepTitle: "اختر اسماً للوكيل",
    nameStepHint:
      "أحرف وأرقام وشرطات فقط — يُحفظ بأحرف صغيرة (مثل code-reviewer)",
    nameStepPlaceholder: "مثل code-reviewer",
    nameStepContinue: "متابعة",
    nameStepInvalidError:
      "اسم غير صالح — استخدم فقط الأحرف، الأرقام والشرطات",
    nameStepAlreadyExistsError: "الاسم مأخوذ مسبقاً، يرجى اختيار اسم آخر",
    nameStepCheckError: "لم أتمكن من التحقق من الاسم — حاول مجدداً",
    nameStepBootstrapMessage:
      "الاسم الجديد لوكيلك هو {name}. دعنا نصف ونهندس روحه الآن.",
    agentCreated: "تم إنشاء الوكيل!",
    startChatting: "ابدأ التحدث معه",
    backToGallery: "العودة للمعرض",
  },

  // Breadcrumb
  breadcrumb: {
    workspace: "مساحة العمل",
    chats: "المحادثات",
  },

  // Workspace
  workspace: {
    officialWebsite: "موقع DeerFlow الرسمي",
    githubTooltip: "DeerFlow على Github",
    settingsAndMore: "الإعدادات والمزيد",
    visitGithub: "تفضل بزيارة GitHub",
    reportIssue: "الإبلاغ عن مشكلة",
    contactUs: "تواصل معنا",
    about: "حول المشروع",
  },

  // Conversation
  conversation: {
    noMessages: "لا توجد رسائل بعد",
    startConversation: "ابدأ المحادثة لترى الرسائل هنا",
  },

  // Chats
  chats: {
    searchChats: "البحث في المحادثات",
  },

  // Page titles (document title)
  pages: {
    appName: "DeerFlow",
    chats: "المحادثات",
    newChat: "محادثة جديدة",
    untitled: "بدون عنوان",
  },

  // Tool calls
  toolCalls: {
    moreSteps: (count: number) => `${count} خطوات إضافية`,
    lessSteps: "إخفاء الخطوات",
    executeCommand: "تنفيذ أمر سطر الأوامر",
    presentFiles: "تصفح الملفات",
    needYourHelp: "بحاجة لمساعدتك",
    useTool: (toolName: string) => `استخدام الأداة "${toolName}"`,
    searchFor: (query: string) => `البحث عن "${query}"`,
    searchForRelatedInfo: "البحث عن معلومات ذات صلة",
    searchForRelatedImages: "البحث عن صور ذات صلة",
    searchForRelatedImagesFor: (query: string) =>
      `البحث عن صور تتعلق بـ "${query}"`,
    searchOnWebFor: (query: string) => `البحث في الويب عن "${query}"`,
    viewWebPage: "زيارة صفحة ويب",
    listFolder: "عرض محتويات المجلد",
    readFile: "قراءة ملف",
    writeFile: "تعديل/إنشاء ملف",
    clickToViewContent: "انقر لعرض محتوى الملف",
    writeTodos: "تحديث قائمة المهام",
    skillInstallTooltip: "تثبيت المهارة وإتاحتها للنظام",
  },

  // Subtasks
  uploads: {
    uploading: "جاري الرفع...",
    uploadingFiles: "جاري رفع الملفات، يرجى الانتظار...",
  },

  subtasks: {
    subtask: "مهمة فرعية",
    executing: (count: number) =>
      `تنفيذ ${count} مهام فرعية بالتوازي`,
    in_progress: "يجري تنفيذ المهمة الفرعية",
    completed: "تم إكمال المهمة الفرعية",
    failed: "فشلت المهمة",
  },

  // Settings
  settings: {
    title: "الإعدادات",
    description: "قم بتخصيص مظهر وتصرفات DeerFlow بما يتناسب معك.",
    sections: {
      appearance: "المظهر",
      memory: "الذاكرة",
      tools: "الأدوات",
      skills: "المهارات",
      notification: "الإشعارات",
      about: "حول",
    },
    memory: {
      title: "الذاكرة",
      description:
        "يبرمج DeerFlow نفسه للتعلم تلقائياً من محادثاتك في الخلفية. هذه الذكريات تساعده على فهمك بشكل أعمق وتقديم تجربة مخصصة لك.",
      empty: "لا توجد بيانات ليتم عرضها.",
      rawJson: "تنسيق JSON",
      markdown: {
        overview: "نظرة عامة",
        userContext: "نبذة عن المستخدم",
        work: "العمل",
        personal: "شخصي",
        topOfMind: "الأفكار الحالية",
        historyBackground: "خلفية تاريخية",
        recentMonths: "مستجدات الأشهر الأخيرة",
        earlierContext: "السياق القديم",
        longTermBackground: "توجهات طويلة الأمد",
        updatedAt: "تاريخ التحديث",
        facts: "معلومات مؤكدة",
        empty: "(فارغ)",
        table: {
          category: "الفئة",
          confidence: "نسبة الثقة",
          confidenceLevel: {
            veryHigh: "عالية جداً",
            high: "عالية",
            normal: "اعتيادية",
            unknown: "غير معروفة",
          },
          content: "المحتوى",
          source: "المصدر",
          createdAt: "تاريخ الإنشاء",
          view: "إظهار",
        },
      },
    },
    appearance: {
      themeTitle: "السمة",
      themeDescription:
        "اختر ما إذا كانت الواجهة تتطابق مع نظامك المتصل أو اختيار ثابت.",
      system: "النظام",
      light: "مضيء",
      dark: "ليل/داكن",
      systemDescription: "التطابق التلقائي مع نظام التشغيل.",
      lightDescription: "لوحة ألوان مشرقة لبيئة العمل النهارية.",
      darkDescription: "لوحة داكنة عالية التباين تساعد على التركيز في وضع الظلام.",
      languageTitle: "اللغة",
      languageDescription: "التبديل بين اللغات المختلفة للنظام.",
    },
    tools: {
      title: "أدوات مخصصة",
      description: "إدارة إعدادات وحالة الأدوات والخوادم لبروتوكول MCP.",
    },
    skills: {
      title: "مهارات الذكاء الاصطناعي",
      description:
        "إدارة إعدادات وتمكين مهارات وقدرات المهام الفرعية للعميل.",
      createSkill: "إنشاء مهارة",
      emptyTitle: "لا توجد أي مهارات متوفرة",
      emptyDescription:
        "قم بوضع ملفات المهام الخاصة بك مجلد /skills/custom من جذر المشروع الرئيسي.",
      emptyButton: "أنشئ مهارتك الاحترافية الأولى",
    },
    notification: {
      title: "الإشعارات",
      description:
        "يقوم النظام بإرسال إشعارات الإكمال فقط عند تنشيط العمليات المطولة في الخلفية لضمان عدم الإزعاج وتتبع سير العمل.",
      requestPermission: "طلب صلاحية الإشعارات",
      deniedHint:
        "لقد تم رفض صلاحية الوصول. يمكنك تفعيلها من إعدادات المتصفح الخاص بك لاستقبال التنبيهات المهمة.",
      testButton: "إرسال إشعار تجريبي",
      testTitle: "DeerFlow",
      testBody: "مرحباً! هذا إشعار تجريبي يعمل بنجاح.",
      notSupported: "متصفحك لا يتمتع بدعم استلام الإشعارات الحديثة.",
      disableNotification: "إيقاف الإشعارات",
    },
    acknowledge: {
      emptyTitle: "إقرارات",
      emptyDescription: "سيتم عرض قائمة الإقرارات للمساهمين هنا.",
    },
  },
};
