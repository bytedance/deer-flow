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

export const ptBR: Translations = {
  locale: {
    localName: "Portugues (Brasil)",
  },

  common: {
    home: "Inicio",
    settings: "Configuracoes",
    delete: "Excluir",
    edit: "Editar",
    rename: "Renomear",
    share: "Compartilhar",
    openInNewWindow: "Abrir em nova janela",
    close: "Fechar",
    more: "Mais",
    search: "Buscar",
    download: "Baixar",
    thinking: "Pensando",
    artifacts: "Artefatos",
    public: "Publico",
    custom: "Personalizado",
    notAvailableInDemoMode: "Indisponivel no modo demo",
    loading: "Carregando...",
    version: "Versao",
    lastUpdated: "Ultima atualizacao",
    code: "Codigo",
    preview: "Visualizacao",
    cancel: "Cancelar",
    save: "Salvar",
    install: "Instalar",
    create: "Criar",
    export: "Exportar",
    exportAsMarkdown: "Exportar em Markdown",
    exportAsJSON: "Exportar em JSON",
    exportSuccess: "Conversa exportada",
    image: "Imagem",
    attachment: "Anexo",
    removeAttachment: "Remover anexo",
    submit: "Enviar",
  },

  welcome: {
    greeting: "Ola de novo!",
    description:
      "Boas-vindas ao 🦌 DeerFlow, um superagente open source. Com skills nativas e personalizadas, o DeerFlow ajuda voce a pesquisar na web, analisar dados e gerar artefatos como apresentacoes, paginas web e praticamente qualquer outra coisa.",
    createYourOwnSkill: "Crie sua propria skill",
    createYourOwnSkillDescription:
      "Crie sua propria skill para liberar todo o potencial do DeerFlow. Com skills personalizadas, ele pode pesquisar na web, analisar dados e gerar artefatos como apresentacoes, paginas web e muito mais.",
  },

  clipboard: {
    copyToClipboard: "Copiar para a area de transferencia",
    copiedToClipboard: "Copiado para a area de transferencia",
    failedToCopyToClipboard: "Falha ao copiar para a area de transferencia",
    linkCopied: "Link copiado para a area de transferencia",
  },

  inputBox: {
    placeholder: "Como posso ajudar voce hoje?",
    createSkillPrompt:
      "Vamos criar uma nova skill passo a passo com `skill-creator`. Para comecar, o que voce quer que essa skill faca?",
    addAttachments: "Adicionar anexos",
    mode: "Modo",
    flashMode: "Flash",
    flashModeDescription: "Rapido e eficiente, mas pode ser menos preciso",
    reasoningMode: "Raciocinio",
    reasoningModeDescription:
      "Pensa antes de agir, equilibrando tempo e precisao",
    proMode: "Pro",
    proModeDescription:
      "Pensa, planeja e executa para resultados mais precisos, embora possa levar mais tempo",
    ultraMode: "Ultra",
    ultraModeDescription:
      "Modo Pro com subagentes para dividir o trabalho; ideal para tarefas complexas com varias etapas",
    reasoningEffort: "Profundidade de raciocinio",
    reasoningEffortMinimal: "Minima",
    reasoningEffortMinimalDescription: "Recuperacao + resposta direta",
    reasoningEffortLow: "Baixa",
    reasoningEffortLowDescription: "Checagem logica simples + deducao superficial",
    reasoningEffortMedium: "Media",
    reasoningEffortMediumDescription:
      "Analise logica em varias camadas + verificacao basica",
    reasoningEffortHigh: "Alta",
    reasoningEffortHighDescription:
      "Deducao completa + verificacao por multiplos caminhos + checagem retroativa",
    searchModels: "Buscar modelos...",
    surpriseMe: "Surpreenda",
    surpriseMePrompt: "Me surpreenda",
    followupLoading: "Gerando perguntas de acompanhamento...",
    followupConfirmTitle: "Enviar sugestao?",
    followupConfirmDescription:
      "Ja existe texto no campo de entrada. Escolha como deseja enviar.",
    followupConfirmAppend: "Anexar e enviar",
    followupConfirmReplace: "Substituir e enviar",
    suggestions: [
      {
        suggestion: "Escrever",
        prompt: "Escreva um post de blog sobre as ultimas tendencias em [tema]",
        icon: PenLineIcon,
      },
      {
        suggestion: "Pesquisar",
        prompt:
          "Faca uma pesquisa aprofundada sobre [tema] e resuma os resultados.",
        icon: MicroscopeIcon,
      },
      {
        suggestion: "Coletar",
        prompt: "Colete dados de [fonte] e crie um relatorio.",
        icon: ShapesIcon,
      },
      {
        suggestion: "Aprender",
        prompt: "Aprenda sobre [tema] e crie um tutorial.",
        icon: GraduationCapIcon,
      },
    ],
    suggestionsCreate: [
      {
        suggestion: "Pagina web",
        prompt: "Crie uma pagina web sobre [tema]",
        icon: CompassIcon,
      },
      {
        suggestion: "Imagem",
        prompt: "Crie uma imagem sobre [tema]",
        icon: ImageIcon,
      },
      {
        suggestion: "Video",
        prompt: "Crie um video sobre [tema]",
        icon: VideoIcon,
      },
      {
        type: "separator",
      },
      {
        suggestion: "Skill",
        prompt:
          "Vamos criar uma nova skill passo a passo com `skill-creator`. Para comecar, o que voce quer que essa skill faca?",
        icon: SparklesIcon,
      },
    ],
  },

  sidebar: {
    recentChats: "Conversas recentes",
    newChat: "Nova conversa",
    chats: "Conversas",
    demoChats: "Conversas de demonstracao",
    agents: "Agentes",
  },

  agents: {
    title: "Agentes",
    description:
      "Crie e gerencie agentes personalizados com prompts e capacidades especializadas.",
    newAgent: "Novo agente",
    emptyTitle: "Ainda nao ha agentes personalizados",
    emptyDescription:
      "Crie seu primeiro agente personalizado com um prompt de sistema especializado.",
    chat: "Conversar",
    delete: "Excluir",
    deleteConfirm:
      "Tem certeza de que deseja excluir este agente? Esta acao nao pode ser desfeita.",
    deleteSuccess: "Agente excluido",
    newChat: "Nova conversa",
    createPageTitle: "Projete seu agente",
    createPageSubtitle:
      "Descreva o agente que voce quer e eu vou ajudar a cria-lo por meio de conversa.",
    nameStepTitle: "Dê um nome ao novo agente",
    nameStepHint:
      "Somente letras, numeros e hifens; o nome sera salvo em minusculas (ex.: code-reviewer)",
    nameStepPlaceholder: "ex.: code-reviewer",
    nameStepContinue: "Continuar",
    nameStepInvalidError:
      "Nome invalido: use apenas letras, numeros e hifens",
    nameStepAlreadyExistsError: "Ja existe um agente com esse nome",
    nameStepCheckError:
      "Nao foi possivel verificar a disponibilidade do nome. Tente novamente.",
    nameStepBootstrapMessage:
      "O nome do novo agente personalizado e {name}. Vamos inicializar a **SOUL** dele.",
    agentCreated: "Agente criado!",
    startChatting: "Comecar a conversar",
    backToGallery: "Voltar para a galeria",
  },

  breadcrumb: {
    workspace: "Workspace",
    chats: "Conversas",
  },

  workspace: {
    officialWebsite: "Site oficial do DeerFlow",
    githubTooltip: "DeerFlow no GitHub",
    settingsAndMore: "Configuracoes e mais",
    visitGithub: "DeerFlow no GitHub",
    reportIssue: "Reportar um problema",
    contactUs: "Fale conosco",
    about: "Sobre o DeerFlow",
  },

  conversation: {
    noMessages: "Ainda nao ha mensagens",
    startConversation: "Inicie uma conversa para ver as mensagens aqui",
  },

  chats: {
    searchChats: "Buscar conversas",
  },

  pages: {
    appName: "DeerFlow",
    chats: "Conversas",
    newChat: "Nova conversa",
    untitled: "Sem titulo",
  },

  toolCalls: {
    moreSteps: (count: number) =>
      `${count} etapa${count === 1 ? "" : "s"} a mais`,
    lessSteps: "Menos etapas",
    executeCommand: "Executar comando",
    presentFiles: "Apresentar arquivos",
    needYourHelp: "Precisa da sua ajuda",
    useTool: (toolName: string) => `Usar a ferramenta "${toolName}"`,
    searchForRelatedInfo: "Buscar informacoes relacionadas",
    searchForRelatedImages: "Buscar imagens relacionadas",
    searchFor: (query: string) => `Buscar por "${query}"`,
    searchForRelatedImagesFor: (query: string) =>
      `Buscar imagens relacionadas a "${query}"`,
    searchOnWebFor: (query: string) => `Buscar na web por "${query}"`,
    viewWebPage: "Ver pagina web",
    listFolder: "Listar pasta",
    readFile: "Ler arquivo",
    writeFile: "Escrever arquivo",
    clickToViewContent: "Clique para ver o conteudo do arquivo",
    writeTodos: "Atualizar lista de tarefas",
    skillInstallTooltip:
      "Instale a skill e deixe-a disponivel para o DeerFlow",
  },

  uploads: {
    uploading: "Enviando...",
    uploadingFiles: "Enviando arquivos, aguarde...",
  },

  subtasks: {
    subtask: "Subtarefa",
    executing: (count: number) =>
      `Executando ${count === 1 ? "" : `${count} `}subtarefa${count === 1 ? "" : "s em paralelo"}`,
    in_progress: "Executando subtarefa",
    completed: "Subtarefa concluida",
    failed: "Subtarefa falhou",
  },

  tokenUsage: {
    title: "Uso de tokens",
    input: "Entrada",
    output: "Saida",
    total: "Total",
    reasoning: "Raciocinio",
    cache: "Cache",
    totalCost: "Custo total",
  },

  shortcuts: {
    searchActions: "Buscar acoes...",
    noResults: "Nenhum resultado encontrado.",
    actions: "Acoes",
    keyboardShortcuts: "Atalhos de teclado",
    keyboardShortcutsDescription:
      "Navegue pelo DeerFlow mais rapido usando atalhos de teclado.",
    openCommandPalette: "Abrir paleta de comandos",
    toggleSidebar: "Alternar barra lateral",
  },

  settings: {
    title: "Configuracoes",
    description: "Ajuste a aparencia e o comportamento do DeerFlow para voce.",
    sections: {
      appearance: "Aparencia",
      memory: "Memoria",
      tools: "Ferramentas",
      skills: "Skills",
      notification: "Notificacoes",
      about: "Sobre",
    },
    memory: {
      title: "Memoria",
      description:
        "O DeerFlow aprende automaticamente com suas conversas em segundo plano. Essas memorias ajudam o DeerFlow a entender voce melhor e a oferecer uma experiencia mais personalizada.",
      empty: "Nenhum dado de memoria para exibir.",
      rawJson: "JSON bruto",
      addFact: "Adicionar fato",
      addFactTitle: "Adicionar fato de memoria",
      editFactTitle: "Editar fato de memoria",
      addFactSuccess: "Fato criado",
      editFactSuccess: "Fato atualizado",
      clearAll: "Limpar toda a memoria",
      clearAllConfirmTitle: "Limpar toda a memoria?",
      clearAllConfirmDescription:
        "Isso removera todos os resumos e fatos salvos. Esta acao nao pode ser desfeita.",
      clearAllSuccess: "Toda a memoria foi limpa",
      factDeleteConfirmTitle: "Excluir este fato?",
      factDeleteConfirmDescription:
        "Este fato sera removido da memoria imediatamente. Esta acao nao pode ser desfeita.",
      factDeleteSuccess: "Fato excluido",
      factContentLabel: "Conteudo",
      factCategoryLabel: "Categoria",
      factConfidenceLabel: "Confianca",
      factContentPlaceholder: "Descreva o fato de memoria que deseja salvar",
      factCategoryPlaceholder: "contexto",
      factConfidenceHint: "Use um numero entre 0 e 1.",
      factSave: "Salvar fato",
      factValidationContent: "O conteudo do fato nao pode ficar vazio.",
      factValidationConfidence:
        "A confianca deve ser um numero entre 0 e 1.",
      manualFactSource: "Manual",
      noFacts: "Ainda nao ha fatos salvos.",
      summaryReadOnly:
        "As secoes de resumo ainda sao somente leitura. No momento, voce pode adicionar, editar ou excluir fatos individuais, ou limpar toda a memoria.",
      memoryFullyEmpty: "Ainda nao ha memoria salva.",
      factPreviewLabel: "Fato a ser excluido",
      searchPlaceholder: "Buscar na memoria",
      filterAll: "Tudo",
      filterFacts: "Fatos",
      filterSummaries: "Resumos",
      noMatches: "Nenhuma memoria correspondente encontrada.",
      markdown: {
        overview: "Visao geral",
        userContext: "Contexto do usuario",
        work: "Trabalho",
        personal: "Pessoal",
        topOfMind: "No radar",
        historyBackground: "Historico",
        recentMonths: "Meses recentes",
        earlierContext: "Contexto anterior",
        longTermBackground: "Contexto de longo prazo",
        updatedAt: "Atualizado em",
        facts: "Fatos",
        empty: "(vazio)",
        table: {
          category: "Categoria",
          confidence: "Confianca",
          confidenceLevel: {
            veryHigh: "Muito alta",
            high: "Alta",
            normal: "Normal",
            unknown: "Desconhecida",
          },
          content: "Conteudo",
          source: "Fonte",
          createdAt: "Criado em",
          view: "Ver",
        },
      },
    },
    appearance: {
      themeTitle: "Tema",
      themeDescription:
        "Escolha se a interface acompanha o sistema ou permanece fixa.",
      system: "Sistema",
      light: "Claro",
      dark: "Escuro",
      systemDescription: "Acompanha automaticamente a preferencia do sistema.",
      lightDescription:
        "Paleta mais clara com maior contraste para uso durante o dia.",
      darkDescription:
        "Paleta mais escura para reduzir brilho e manter o foco.",
      languageTitle: "Idioma",
      languageDescription: "Alterne entre os idiomas disponiveis.",
    },
    tools: {
      title: "Ferramentas",
      description:
        "Gerencie a configuracao e o estado de habilitacao das ferramentas MCP.",
    },
    skills: {
      title: "Skills do agente",
      description:
        "Gerencie a configuracao e o estado de habilitacao das skills do agente.",
      createSkill: "Criar skill",
      emptyTitle: "Ainda nao ha skills do agente",
      emptyDescription:
        "Coloque as pastas das suas skills em `/skills/custom`, na raiz do DeerFlow.",
      emptyButton: "Crie sua primeira skill",
    },
    notification: {
      title: "Notificacoes",
      description:
        "O DeerFlow so envia notificacoes de conclusao quando a janela nao esta ativa. Isso e especialmente util para tarefas longas, para que voce possa trabalhar em outra coisa e ser avisado quando terminar.",
      requestPermission: "Solicitar permissao para notificacoes",
      deniedHint:
        "A permissao para notificacoes foi negada. Voce pode habilita-la nas configuracoes do site do navegador para receber alertas de conclusao.",
      testButton: "Enviar notificacao de teste",
      testTitle: "DeerFlow",
      testBody: "Esta e uma notificacao de teste.",
      notSupported: "Seu navegador nao suporta notificacoes.",
      disableNotification: "Desativar notificacoes",
    },
    acknowledge: {
      emptyTitle: "Agradecimentos",
      emptyDescription: "Creditos e agradecimentos aparecerao aqui.",
    },
  },
};
