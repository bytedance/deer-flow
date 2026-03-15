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

export const ruRU: Translations = {
  // Locale meta
  locale: {
    localName: "Русский",
  },

  // Common
  common: {
    home: "Главная",
    settings: "Настройки",
    delete: "Удалить",
    rename: "Переименовать",
    share: "Поделиться",
    openInNewWindow: "Открыть в новом окне",
    close: "Закрыть",
    more: "Ещё",
    search: "Поиск",
    download: "Скачать",
    thinking: "Размышляю",
    artifacts: "Артефакты",
    public: "Публичный",
    custom: "Пользовательский",
    notAvailableInDemoMode: "Недоступно в демо-режиме",
    loading: "Загрузка...",
    version: "Версия",
    lastUpdated: "Обновлено",
    code: "Код",
    preview: "Предпросмотр",
    cancel: "Отмена",
    save: "Сохранить",
    install: "Установить",
    create: "Создать",
  },

  // Welcome
  welcome: {
    greeting: "Привет! Чем займёмся?",
    description:
      "Aitouch — мультимодальный ИИ-агент для маркетинга. Исследует рынок, создаёт контент, анализирует данные и генерирует лендинги, презентации и рекламные кампании.",

    createYourOwnSkill: "Создайте собственный навык",
    createYourOwnSkillDescription:
      "Создайте собственный навык и раскройте всю мощь DeerFlow. С помощью кастомных навыков\nDeerFlow поможет вам искать в интернете, анализировать данные и создавать\nартефакты: слайды, веб-страницы и многое другое.",
  },

  // Clipboard
  clipboard: {
    copyToClipboard: "Копировать",
    copiedToClipboard: "Скопировано",
    failedToCopyToClipboard: "Ошибка копирования",
    linkCopied: "Ссылка скопирована",
  },

  // Input Box
  inputBox: {
    placeholder: "Чем могу помочь?",
    createSkillPrompt:
      "Мы собираемся создать новый навык шаг за шагом с помощью `skill-creator`. С чего начнём — что должен делать этот навык?",
    addAttachments: "Добавить вложение",
    mode: "Режим",
    flashMode: "Быстрый",
    flashModeDescription: "Быстро и эффективно, точность может быть ниже",
    reasoningMode: "Рассуждение",
    reasoningModeDescription:
      "Рассуждает перед действием, баланс между скоростью и точностью",
    proMode: "Про",
    proModeDescription:
      "Рассуждение, планирование и выполнение — более точные результаты, может занять больше времени",
    ultraMode: "Ультра",
    ultraModeDescription:
      "Про-режим с суб-агентами для разделения задач; лучше всего для сложных многошаговых задач",
    reasoningEffort: "Уровень рассуждений",
    reasoningEffortMinimal: "Минимальный",
    reasoningEffortMinimalDescription: "Поиск + прямой вывод",
    reasoningEffortLow: "Низкий",
    reasoningEffortLowDescription: "Простая логическая проверка + поверхностный вывод",
    reasoningEffortMedium: "Средний",
    reasoningEffortMediumDescription:
      "Многоуровневый логический анализ + базовая верификация",
    reasoningEffortHigh: "Высокий",
    reasoningEffortHighDescription:
      "Полная логическая дедукция + многопутевая верификация + обратная проверка",
    searchModels: "Найти модель...",
    surpriseMe: "Сюрприз",
    surpriseMePrompt: "Удиви меня",
    followupLoading: "Генерирую продолжения...",
    followupConfirmTitle: "Отправить подсказку?",
    followupConfirmDescription:
      "В поле ввода уже есть текст. Выберите способ отправки.",
    followupConfirmAppend: "Добавить и отправить",
    followupConfirmReplace: "Заменить и отправить",
    suggestions: [
      {
        suggestion: "Написать",
        prompt: "Напиши статью в блог о последних тенденциях в [теме]",
        icon: PenLineIcon,
      },
      {
        suggestion: "Исследовать",
        prompt:
          "Проведи глубокое исследование по [теме] и обобщи результаты.",
        icon: MicroscopeIcon,
      },
      {
        suggestion: "Собрать",
        prompt: "Собери данные из [источника] и создай отчёт.",
        icon: ShapesIcon,
      },
      {
        suggestion: "Изучить",
        prompt: "Изучи [тему] и создай обучающий материал.",
        icon: GraduationCapIcon,
      },
    ],
    suggestionsCreate: [
      {
        suggestion: "Веб-страница",
        prompt: "Создай веб-страницу на тему [тема]",
        icon: CompassIcon,
      },
      {
        suggestion: "Изображение",
        prompt: "Создай изображение на тему [тема]",
        icon: ImageIcon,
      },
      {
        suggestion: "Видео",
        prompt: "Создай видео на тему [тема]",
        icon: VideoIcon,
      },
      {
        type: "separator",
      },
      {
        suggestion: "Навык",
        prompt:
          "Мы собираемся создать новый навык шаг за шагом с помощью `skill-creator`. С чего начнём — что должен делать этот навык?",
        icon: SparklesIcon,
      },
    ],
  },

  // Sidebar
  sidebar: {
    newChat: "Новый чат",
    chats: "Чаты",
    recentChats: "Недавние чаты",
    demoChats: "Демо-чаты",
    agents: "Агенты",
  },

  // Agents
  agents: {
    title: "Агенты",
    description:
      "Создавайте и управляйте кастомными агентами со специализированными промптами и возможностями.",
    newAgent: "Новый агент",
    emptyTitle: "Кастомных агентов пока нет",
    emptyDescription:
      "Создайте первого кастомного агента со специализированным системным промптом.",
    chat: "Чат",
    delete: "Удалить",
    deleteConfirm:
      "Вы уверены, что хотите удалить этого агента? Это действие необратимо.",
    deleteSuccess: "Агент удалён",
    newChat: "Новый чат",
    createPageTitle: "Создайте своего агента",
    createPageSubtitle:
      "Опишите нужного агента — я помогу создать его через диалог.",
    nameStepTitle: "Назовите нового агента",
    nameStepHint:
      "Буквы (в т.ч. русские), цифры, дефис и подчёркивание (например: новостник или code-reviewer)",
    nameStepPlaceholder: "например: новостник или code-reviewer",
    nameStepContinue: "Продолжить",
    nameStepInvalidError:
      "Недопустимое имя — используйте буквы, цифры, дефис или подчёркивание",
    nameStepAlreadyExistsError: "Агент с таким именем уже существует",
    nameStepCheckError: "Не удалось проверить доступность имени — попробуйте ещё раз",
    nameStepBootstrapMessage:
      "Новый агент называется {name}. Давайте настроим его **SOUL**.",
    agentCreated: "Агент создан!",
    startChatting: "Начать чат",
    backToGallery: "Назад к галерее",
  },

  // Breadcrumb
  breadcrumb: {
    workspace: "Рабочее пространство",
    chats: "Чаты",
  },

  // Workspace
  workspace: {
    officialWebsite: "Официальный сайт DeerFlow",
    githubTooltip: "DeerFlow на Github",
    settingsAndMore: "Настройки и прочее",
    visitGithub: "DeerFlow на GitHub",
    reportIssue: "Сообщить о проблеме",
    contactUs: "Связаться с нами",
    about: "О DeerFlow",
  },

  // Conversation
  conversation: {
    noMessages: "Сообщений пока нет",
    startConversation: "Начните разговор, чтобы увидеть сообщения",
  },

  // Chats
  chats: {
    searchChats: "Поиск чатов",
  },

  // Page titles
  pages: {
    appName: "DeerFlow",
    chats: "Чаты",
    newChat: "Новый чат",
    untitled: "Без названия",
  },

  // Tool calls
  toolCalls: {
    moreSteps: (count: number) => `Ещё ${count} ${count === 1 ? "шаг" : count < 5 ? "шага" : "шагов"}`,
    lessSteps: "Свернуть шаги",
    executeCommand: "Выполнить команду",
    presentFiles: "Показать файлы",
    needYourHelp: "Требуется ваша помощь",
    useTool: (toolName: string) => `Использую инструмент "${toolName}"`,
    searchFor: (query: string) => `Ищу "${query}"`,
    searchForRelatedInfo: "Ищу связанную информацию",
    searchForRelatedImages: "Ищу связанные изображения",
    searchForRelatedImagesFor: (query: string) =>
      `Ищу изображения по запросу "${query}"`,
    searchOnWebFor: (query: string) => `Ищу в интернете "${query}"`,
    viewWebPage: "Просматриваю страницу",
    listFolder: "Просматриваю папку",
    readFile: "Читаю файл",
    writeFile: "Записываю файл",
    clickToViewContent: "Нажмите, чтобы открыть содержимое файла",
    writeTodos: "Обновляю список задач",
    skillInstallTooltip: "Установить навык и сделать его доступным для DeerFlow",
  },

  // Uploads
  uploads: {
    uploading: "Загрузка...",
    uploadingFiles: "Загружаю файлы, подождите...",
  },

  // Subtasks
  subtasks: {
    subtask: "Подзадача",
    executing: (count: number) =>
      `Выполняю ${count === 1 ? "" : count + " "}${count === 1 ? "подзадачу" : count < 5 ? "подзадачи параллельно" : "подзадач параллельно"}`,
    in_progress: "Выполняю подзадачу",
    completed: "Подзадача выполнена",
    failed: "Подзадача завершилась ошибкой",
  },

  // Settings
  settings: {
    title: "Настройки",
    description: "Настройте внешний вид и поведение DeerFlow.",
    sections: {
      appearance: "Внешний вид",
      memory: "Память",
      tools: "Инструменты",
      skills: "Навыки",
      notification: "Уведомления",
      about: "О приложении",
    },
    memory: {
      title: "Память",
      description:
        "DeerFlow автоматически учится на основе ваших разговоров в фоновом режиме. Эти воспоминания помогают DeerFlow лучше вас понимать и создавать более персонализированный опыт.",
      empty: "Данных памяти нет.",
      rawJson: "Сырой JSON",
      markdown: {
        overview: "Обзор",
        userContext: "Контекст пользователя",
        work: "Работа",
        personal: "Личное",
        topOfMind: "Актуальное",
        historyBackground: "История",
        recentMonths: "Последние месяцы",
        earlierContext: "Ранний контекст",
        longTermBackground: "Долгосрочный контекст",
        updatedAt: "Обновлено",
        facts: "Факты",
        empty: "(пусто)",
        table: {
          category: "Категория",
          confidence: "Уверенность",
          confidenceLevel: {
            veryHigh: "Очень высокая",
            high: "Высокая",
            normal: "Обычная",
            unknown: "Неизвестно",
          },
          content: "Содержимое",
          source: "Источник",
          createdAt: "Создано",
          view: "Просмотр",
        },
      },
    },
    appearance: {
      themeTitle: "Тема",
      themeDescription:
        "Выберите, следовать ли системной теме или зафиксировать её.",
      system: "Системная",
      light: "Светлая",
      dark: "Тёмная",
      systemDescription: "Автоматически следует настройкам операционной системы.",
      lightDescription: "Светлая палитра с высоким контрастом для дневного использования.",
      darkDescription: "Тёмная палитра для снижения нагрузки на глаза.",
      languageTitle: "Язык",
      languageDescription: "Переключение между языками.",
    },
    tools: {
      title: "Инструменты",
      description: "Управление конфигурацией и состоянием инструментов MCP.",
    },
    skills: {
      title: "Навыки агента",
      description:
        "Управление конфигурацией и состоянием навыков агента.",
      createSkill: "Создать навык",
      emptyTitle: "Навыков агента пока нет",
      emptyDescription:
        "Поместите папки с навыками в каталог `/skills/custom` в корневой папке DeerFlow.",
      emptyButton: "Создать первый навык",
    },
    notification: {
      title: "Уведомления",
      description:
        "DeerFlow отправляет уведомление о завершении только когда окно неактивно. Это удобно для длительных задач — вы можете переключиться на другую работу и получить уведомление по завершении.",
      requestPermission: "Запросить разрешение на уведомления",
      deniedHint:
        "Разрешение на уведомления отклонено. Включите его в настройках сайта в браузере.",
      testButton: "Отправить тестовое уведомление",
      testTitle: "DeerFlow",
      testBody: "Это тестовое уведомление.",
      notSupported: "Ваш браузер не поддерживает уведомления.",
      disableNotification: "Отключить уведомления",
    },
    acknowledge: {
      emptyTitle: "Благодарности",
      emptyDescription: "Кредиты и благодарности будут отображаться здесь.",
    },
  },
};
