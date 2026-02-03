/**
 * Internationalization (i18n) support
 */

export type Language = 'zh' | 'en' | 'ru' | 'es' | 'id' | 'pt' | 'ja' | 'ko';

export const translations = {
  zh: {
    // App
    appTitle: 'KiroaaS',
    dashboard: '仪表盘',

    // Tabs
    tabSettings: '设置',
    tabLogs: '日志',

    // Server Control
    serverControl: '服务器控制',
    serverControlDesc: '管理 KiroaaS 服务器',
    startServer: '启动服务器',
    stopServer: '停止服务器',
    starting: '正在启动...',
    stopping: '正在停止...',
    runningOnPort: '运行端口',
    configureApiKeyFirst: '请先在设置标签页配置 API 密钥，然后再启动服务器',
    startServerFailed: '启动服务器失败',
    stopServerFailed: '停止服务器失败',

    // Status
    statusStopped: '已停止',
    statusStarting: '启动中',
    statusRunning: '运行中',
    statusError: '错误',

    // Settings Form
    authSettings: '认证设置',
    authMethod: '认证方式',
    authRefreshToken: '刷新令牌',
    authCredsFile: '凭证文件',
    authCliDb: 'Kiro CLI 数据库',
    refreshToken: '刷新令牌',
    refreshTokenPlaceholder: '输入你的刷新令牌',
    credsFilePath: '凭证文件路径',
    cliDbPath: 'Kiro CLI 数据库路径',

    securitySettings: '安全设置',
    proxyApiKey: '代理 API 密钥',
    proxyApiKeyPlaceholder: '你的超级密钥',
    proxyApiKeyDesc: '访问网关 API 时需要此密钥',
    generate: '生成',
    generateApiKey: '随机生成 API 密钥',

    serverSettings: '服务器设置',
    host: '主机地址',
    port: '端口',
    region: '区域',
    regionUsEast: '美国东部 (弗吉尼亚)',
    regionUsWest: '美国西部 (俄勒冈)',
    regionEuWest: '欧洲 (爱尔兰)',
    regionApSoutheast: '亚太 (新加坡)',

    saveSettings: '保存设置',
    saving: '保存中...',
    saveSuccess: '设置保存成功！',
    saveFailed: '保存设置失败',

    // Credential scanning
    scanCredentials: '扫描凭证',
    scanningCredentials: '正在扫描...',
    foundCredentials: '找到 {count} 个凭证文件',
    noCredentialsFound: '未找到凭证文件',
    selectCredential: '选择凭证文件',
    scanFailed: '扫描失败',
    credentialsFound: '检测到凭证文件',
    autoDetectedCredentials: '我们在您的系统中自动检测到以下凭证：',
    useRecommended: '使用推荐配置',
    dismiss: '忽略',
    confirm: '确认',
    found: '个',

    // Advanced Settings
    advancedSettings: '高级设置',
    vpnProxy: 'VPN/代理',
    vpnProxyUrl: 'VPN 代理地址',
    vpnProxyUrlPlaceholder: 'http://proxy.example.com:8080',
    vpnProxyUrlDesc: '可选的 VPN 代理服务器地址',

    timeoutSettings: '超时设置',
    firstTokenTimeout: '首个令牌超时 (秒)',
    streamingReadTimeout: '流式读取超时 (秒)',

    featureSettings: '功能设置',
    enableFakeReasoning: '启用模拟推理',
    maxTokens: '最大令牌数',
    enableTruncationRecovery: '启用截断恢复',

    logSettings: '日志设置',
    logLevel: '日志级别',
    logDebug: '调试',
    logInfo: '信息',
    logWarning: '警告',
    logError: '错误',
    debugMode: '调试模式',
    debugOff: '关闭',
    debugOn: '开启',
    debugVerbose: '详细',

    // Log Viewer
    serverLogs: '服务器日志',
    autoScroll: '自动滚动',
    export: '导出',
    clear: '清除',
    noLogs: '暂无日志启动服务器后将显示日志',

    // Footer
    reportIssue: '报告问题',

    // Errors
    configError: '配置错误',
    loadingConfig: '正在加载配置...',
    retry: '重试',

    // Language
    language: '语言',

    // Dashboard
    operations: '运营中心',
    systemLogs: '系统日志',
    configurationError: '配置错误',
    dashboardDesc: '在此管理您的网关和连接状态',
    settingsDesc: '配置认证和代理设置',
    logsDesc: '实时服务器活动',
    gatewayStatus: '网关状态',
    active: '活跃',
    offline: '离线',
    online: 'ONLINE',
    stopped: 'STOPPED',
    servingOnPort: '正在端口 {port} 上提供服务',
    readyToInitialize: '准备初始化连接',
    listeningPort: '监听端口',
    auth: '认证方式',
    auto: '自动',
    liveActivity: '实时活动',
    expand: '展开',
    waitingForEvents: '等待服务器事件...',
    advanced: '高级',
    proTip: '提示',
    proTipDesc: '如果您没有管理员提供的代理 API 密钥，请使用"生成"按钮生成一个安全的密钥',
    administrator: '管理员',

    // API Examples
    apiExamples: 'API 示例',
    copy: '复制',
    copied: '已复制',

    // Chat
    tabChat: '对话',
    chatDesc: '与 AI 模型进行对话',
    chatWelcome: '开始对话',
    chatWelcomeDesc: '发送消息开始与 AI 对话',
    chatPlaceholder: '输入消息...',
    chatServerOffline: '服务器离线',
    chatServerOfflineDesc: '请先启动服务器',
    chatError: '发送消息失败',

    // CC Switch Import
    ccSwitchImport: '导入到 CC Switch',
    ccSwitchIntro: 'CC Switch 是一个 Claude Code 配置管理工具，可以快速切换不同的 API Provider。',
    ccSwitchImportDesc: '一键将此配置导入到 CC Switch，让 Claude Code 使用 KiroaaS 网关。',
    importToCCSwitch: '导入到 CC Switch',
    importing: '正在导入...',
    importSuccess: '导入成功',
    notConfigured: '未配置',

    // Settings Form
    authenticationMethod: '认证方式',
    howGatewayConnects: '网关如何连接到 Kiro 服务',
    sqliteDatabasePath: 'SQLite 数据库路径',
    credentialsFilePath: '凭证文件路径',
    security: '安全',
    protectEndpoint: '保护您的网关端点',
    hide: '隐藏',
    show: '显示',
    realValue: '真实值',
    clientsIncludeKey: '客户端（如 Cursor 或 VS Code）必须在 Authorization 头中包含此密钥',
    savedSuccessfully: '保存成功',
    savingChanges: '正在保存...',
    saveConfiguration: '保存配置',

    // Log Viewer
    systemOutput: '系统输出',
    eventsCaptured: '{count} 个事件已捕获',
    live: '实时',
    paused: '已暂停',
    noLogsAvailable: '暂无日志可显示',
    resumeFeed: '恢复订阅',

    // Advanced Settings
    vpnProxyTunnel: 'VPN / 代理隧道',
    timeoutsSeconds: '超时（秒）',
    firstToken: '首个令牌',
    streamRead: '流式读取',
    serverPort: '服务器端口',
  },
  en: {
    // App
    appTitle: 'KiroaaS',
    dashboard: 'Dashboard',

    // Tabs
    tabSettings: 'Settings',
    tabLogs: 'Logs',

    // Server Control
    serverControl: 'Server Control',
    serverControlDesc: 'Manage KiroaaS server',
    startServer: 'Start Server',
    stopServer: 'Stop Server',
    starting: 'Starting...',
    stopping: 'Stopping...',
    runningOnPort: 'Running on port',
    configureApiKeyFirst: 'Please configure your API key in the Settings tab before starting the server.',
    startServerFailed: 'Failed to start server',
    stopServerFailed: 'Failed to stop server',

    // Status
    statusStopped: 'Stopped',
    statusStarting: 'Starting',
    statusRunning: 'Running',
    statusError: 'Error',

    // Settings Form
    authSettings: 'Authentication',
    authMethod: 'Authentication Method',
    authRefreshToken: 'Refresh Token',
    authCredsFile: 'Credentials File',
    authCliDb: 'Kiro CLI Database',
    refreshToken: 'Refresh Token',
    refreshTokenPlaceholder: 'Enter your refresh token',
    credsFilePath: 'Credentials File Path',
    cliDbPath: 'Kiro CLI Database Path',

    securitySettings: 'Security',
    proxyApiKey: 'Proxy API Key',
    proxyApiKeyPlaceholder: 'Your super-secret key',
    proxyApiKeyDesc: 'This key is required to access the gateway API',
    generate: 'Generate',
    generateApiKey: 'Generate random API key',

    serverSettings: 'Server',
    host: 'Host',
    port: 'Port',
    region: 'Region',
    regionUsEast: 'US East (N. Virginia)',
    regionUsWest: 'US West (Oregon)',
    regionEuWest: 'EU (Ireland)',
    regionApSoutheast: 'Asia Pacific (Singapore)',

    saveSettings: 'Save Settings',
    saving: 'Saving...',
    saveSuccess: 'Settings saved successfully!',
    saveFailed: 'Failed to save settings',

    // Credential scanning
    scanCredentials: 'Scan Credentials',
    scanningCredentials: 'Scanning...',
    foundCredentials: 'Found {count} credential file(s)',
    noCredentialsFound: 'No credential files found',
    selectCredential: 'Select Credential File',
    scanFailed: 'Scan failed',
    credentialsFound: 'Credentials Detected',
    autoDetectedCredentials: 'We automatically detected the following credentials on your system:',
    useRecommended: 'Use Recommended',
    dismiss: 'Dismiss',
    confirm: 'Confirm',
    found: 'found',

    // Advanced Settings
    advancedSettings: 'Advanced Settings',
    vpnProxy: 'VPN/Proxy',
    vpnProxyUrl: 'VPN Proxy URL',
    vpnProxyUrlPlaceholder: 'http://proxy.example.com:8080',
    vpnProxyUrlDesc: 'Optional proxy server for VPN connections',

    timeoutSettings: 'Timeouts',
    firstTokenTimeout: 'First Token Timeout (seconds)',
    streamingReadTimeout: 'Streaming Read Timeout (seconds)',

    featureSettings: 'Features',
    enableFakeReasoning: 'Enable Fake Reasoning',
    maxTokens: 'Max Tokens',
    enableTruncationRecovery: 'Enable Truncation Recovery',

    logSettings: 'Logging',
    logLevel: 'Log Level',
    logDebug: 'DEBUG',
    logInfo: 'INFO',
    logWarning: 'WARNING',
    logError: 'ERROR',
    debugMode: 'Debug Mode',
    debugOff: 'Off',
    debugOn: 'On',
    debugVerbose: 'Verbose',

    // Log Viewer
    serverLogs: 'Server Logs',
    autoScroll: 'Auto-scroll',
    export: 'Export',
    clear: 'Clear',
    noLogs: 'No logs yet. Start the server to see logs.',

    // Footer
    reportIssue: 'Report Issue',

    // Errors
    configError: 'Configuration Error',
    loadingConfig: 'Loading configuration...',
    retry: 'Retry',

    // Language
    language: 'Language',

    // Dashboard
    operations: 'Operations',
    systemLogs: 'System Logs',
    configurationError: 'Configuration Error',
    dashboardDesc: 'Manage your gateway and connection status here.',
    settingsDesc: 'Configure authentication and proxy settings.',
    logsDesc: 'Real-time server activity streaming.',
    gatewayStatus: 'GATEWAY STATUS',
    active: 'Active',
    offline: 'Offline',
    online: 'ONLINE',
    stopped: 'STOPPED',
    servingOnPort: 'Serving requests on port {port}',
    readyToInitialize: 'Ready to initialize connection',
    listeningPort: 'Listening Port',
    auth: 'Auth',
    auto: 'AUTO',
    liveActivity: 'Live Activity',
    expand: 'Expand',
    waitingForEvents: 'Waiting for server events...',
    advanced: 'Advanced',
    proTip: 'Tip',
    proTipDesc: 'Use the "Generate" button for a secure Proxy API Key if you don\'t have one provided by your administrator.',
    administrator: 'Administrator',

    // API Examples
    apiExamples: 'API Examples',
    copy: 'Copy',
    copied: 'Copied',

    // Chat
    tabChat: 'Chat',
    chatDesc: 'Chat with AI models.',
    chatWelcome: 'Start a conversation',
    chatWelcomeDesc: 'Send a message to start chatting with AI',
    chatPlaceholder: 'Type a message...',
    chatServerOffline: 'Server offline',
    chatServerOfflineDesc: 'Please start the server first',
    chatError: 'Failed to send message',

    // CC Switch Import
    ccSwitchImport: 'Import to CC Switch',
    ccSwitchIntro: 'CC Switch is a Claude Code configuration manager that allows quick switching between different API Providers.',
    ccSwitchImportDesc: 'One-click import this configuration to CC Switch, enabling Claude Code to use the KiroaaS gateway.',
    importToCCSwitch: 'Import to CC Switch',
    importing: 'Importing...',
    importSuccess: 'Import Success',
    notConfigured: 'Not configured',

    // Settings Form
    authenticationMethod: 'Authentication Method',
    howGatewayConnects: 'How the gateway connects to Kiro services.',
    sqliteDatabasePath: 'SQLite Database Path',
    credentialsFilePath: 'Credentials File Path',
    security: 'Security',
    protectEndpoint: 'Protect your gateway endpoint.',
    hide: 'Hide',
    show: 'Show',
    realValue: 'Real Value',
    clientsIncludeKey: 'Clients (like Cursor or VS Code) must include this key in the Authorization header.',
    savedSuccessfully: 'Saved Successfully',
    savingChanges: 'Saving Changes...',
    saveConfiguration: 'Save Configuration',

    // Log Viewer
    systemOutput: 'System Output',
    eventsCaptured: '{count} events captured',
    live: 'Live',
    paused: 'Paused',
    noLogsAvailable: 'No logs available to display',
    resumeFeed: 'Resume Feed',

    // Advanced Settings
    vpnProxyTunnel: 'VPN / Proxy Tunnel',
    timeoutsSeconds: 'Timeouts (seconds)',
    firstToken: 'First Token',
    streamRead: 'Stream Read',
    serverPort: 'Server Port',
  },
  ru: {
    // App
    appTitle: 'KiroaaS',
    dashboard: 'Панель',

    // Tabs
    tabSettings: 'Настройки',
    tabLogs: 'Журналы',

    // Server Control
    serverControl: 'Управление сервером',
    serverControlDesc: 'Управляйте сервером KiroaaS',
    startServer: 'Запустить сервер',
    stopServer: 'Остановить сервер',
    starting: 'Запуск...',
    stopping: 'Остановка...',
    runningOnPort: 'Работает на порту',
    configureApiKeyFirst:
      'Сначала настройте API‑ключ на вкладке «Настройки», затем запускайте сервер.',
    startServerFailed: 'Не удалось запустить сервер',
    stopServerFailed: 'Не удалось остановить сервер',

    // Status
    statusStopped: 'Остановлен',
    statusStarting: 'Запускается',
    statusRunning: 'Работает',
    statusError: 'Ошибка',

    // Settings Form
    authSettings: 'Аутентификация',
    authMethod: 'Способ аутентификации',
    authRefreshToken: 'Токен обновления',
    authCredsFile: 'Файл учётных данных',
    authCliDb: 'База данных Kiro CLI',
    refreshToken: 'Токен обновления',
    refreshTokenPlaceholder: 'Введите токен обновления',
    credsFilePath: 'Путь к файлу учётных данных',
    cliDbPath: 'Путь к базе данных Kiro CLI',

    securitySettings: 'Безопасность',
    proxyApiKey: 'API‑ключ прокси',
    proxyApiKeyPlaceholder: 'Ваш сверхсекретный ключ',
    proxyApiKeyDesc: 'Этот ключ нужен для доступа к API шлюза',
    generate: 'Сгенерировать',
    generateApiKey: 'Сгенерировать случайный API‑ключ',

    serverSettings: 'Сервер',
    host: 'Хост',
    port: 'Порт',
    region: 'Регион',
    regionUsEast: 'США Восток (Сев. Вирджиния)',
    regionUsWest: 'США Запад (Орегон)',
    regionEuWest: 'ЕС (Ирландия)',
    regionApSoutheast: 'Азиатско‑Тихоокеанский регион (Сингапур)',

    saveSettings: 'Сохранить настройки',
    saving: 'Сохранение...',
    saveSuccess: 'Настройки успешно сохранены!',
    saveFailed: 'Не удалось сохранить настройки',

    // Credential scanning
    scanCredentials: 'Сканировать учётные данные',
    scanningCredentials: 'Сканирование...',
    foundCredentials: 'Найдено файлов учётных данных: {count}',
    noCredentialsFound: 'Файлы учётных данных не найдены',
    selectCredential: 'Выбрать файл учётных данных',
    scanFailed: 'Сканирование не удалось',
    credentialsFound: 'Учётные данные обнаружены',
    autoDetectedCredentials:
      'Мы автоматически обнаружили следующие учётные данные в вашей системе:',
    useRecommended: 'Использовать рекомендованное',
    dismiss: 'Пропустить',
    confirm: 'Подтвердить',
    found: 'найдено',

    // Advanced Settings
    advancedSettings: 'Расширенные настройки',
    vpnProxy: 'VPN/Прокси',
    vpnProxyUrl: 'URL VPN‑прокси',
    vpnProxyUrlPlaceholder: 'http://proxy.example.com:8080',
    vpnProxyUrlDesc: 'Необязательный адрес прокси‑сервера для VPN',

    timeoutSettings: 'Тайм‑ауты',
    firstTokenTimeout: 'Тайм‑аут первого токена (сек.)',
    streamingReadTimeout: 'Тайм‑аут чтения стрима (сек.)',

    featureSettings: 'Функции',
    enableFakeReasoning: 'Включить имитацию рассуждений',
    maxTokens: 'Макс. токенов',
    enableTruncationRecovery: 'Включить восстановление при усечении',

    logSettings: 'Логирование',
    logLevel: 'Уровень логов',
    logDebug: 'Отладка',
    logInfo: 'Информация',
    logWarning: 'Предупреждение',
    logError: 'Ошибка',
    debugMode: 'Режим отладки',
    debugOff: 'Выкл.',
    debugOn: 'Вкл.',
    debugVerbose: 'Подробно',

    // Log Viewer
    serverLogs: 'Логи сервера',
    autoScroll: 'Автопрокрутка',
    export: 'Экспорт',
    clear: 'Очистить',
    noLogs: 'Логов пока нет. Запустите сервер, чтобы увидеть их.',

    // Footer
    reportIssue: 'Сообщить о проблеме',

    // Errors
    configError: 'Ошибка конфигурации',
    loadingConfig: 'Загрузка конфигурации...',
    retry: 'Повторить',

    // Language
    language: 'Язык',

    // Dashboard
    operations: 'Операции',
    systemLogs: 'Системные журналы',
    configurationError: 'Ошибка конфигурации',
    dashboardDesc: 'Управляйте шлюзом и состоянием подключения здесь.',
    settingsDesc: 'Настройте аутентификацию и параметры прокси.',
    logsDesc: 'Поток активности сервера в реальном времени.',
    gatewayStatus: 'СОСТОЯНИЕ ШЛЮЗА',
    active: 'Активен',
    offline: 'Офлайн',
    online: 'В СЕТИ',
    stopped: 'ОСТАНОВЛЕН',
    servingOnPort: 'Обслуживание запросов на порту {port}',
    readyToInitialize: 'Готов к инициализации подключения',
    listeningPort: 'Порт прослушивания',
    auth: 'Аутентификация',
    auto: 'АВТО',
    liveActivity: 'Активность',
    expand: 'Развернуть',
    waitingForEvents: 'Ожидание событий сервера...',
    advanced: 'Расширенное',
    proTip: 'Совет',
    proTipDesc:
      'Если у вас нет API‑ключа прокси от администратора, используйте кнопку «Сгенерировать», чтобы создать безопасный ключ.',
    administrator: 'Администратор',

    // API Examples
    apiExamples: 'Примеры API',
    copy: 'Копировать',
    copied: 'Скопировано',

    // Chat
    tabChat: 'Чат',
    chatDesc: 'Общайтесь с моделями ИИ.',
    chatWelcome: 'Начать разговор',
    chatWelcomeDesc: 'Отправьте сообщение, чтобы начать общение с ИИ',
    chatPlaceholder: 'Введите сообщение...',
    chatServerOffline: 'Сервер офлайн',
    chatServerOfflineDesc: 'Сначала запустите сервер',
    chatError: 'Не удалось отправить сообщение',

    // CC Switch Import
    ccSwitchImport: 'Импорт в CC Switch',
    ccSwitchIntro: 'CC Switch — это менеджер конфигурации Claude Code, позволяющий быстро переключаться между разными API-провайдерами.',
    ccSwitchImportDesc: 'Импортируйте эту конфигурацию в CC Switch одним кликом, чтобы Claude Code использовал шлюз KiroaaS.',
    importToCCSwitch: 'Импорт в CC Switch',
    importing: 'Импорт...',
    importSuccess: 'Импорт успешен',
    notConfigured: 'Не настроено',

    // Settings Form
    authenticationMethod: 'Способ аутентификации',
    howGatewayConnects: 'Как шлюз подключается к сервисам Kiro.',
    sqliteDatabasePath: 'Путь к базе данных SQLite',
    credentialsFilePath: 'Путь к файлу учётных данных',
    security: 'Безопасность',
    protectEndpoint: 'Защитите конечную точку вашего шлюза.',
    hide: 'Скрыть',
    show: 'Показать',
    realValue: 'Реальное значение',
    clientsIncludeKey:
      'Клиенты (например, Cursor или VS Code) должны передавать этот ключ в заголовке Authorization.',
    savedSuccessfully: 'Успешно сохранено',
    savingChanges: 'Сохранение...',
    saveConfiguration: 'Сохранить конфигурацию',

    // Log Viewer
    systemOutput: 'Вывод системы',
    eventsCaptured: 'Событий захвачено: {count}',
    live: 'В эфире',
    paused: 'Пауза',
    noLogsAvailable: 'Нет доступных логов для отображения',
    resumeFeed: 'Возобновить поток',

    // Advanced Settings
    vpnProxyTunnel: 'VPN / Прокси‑туннель',
    timeoutsSeconds: 'Тайм‑ауты (сек.)',
    firstToken: 'Первый токен',
    streamRead: 'Чтение стрима',
    serverPort: 'Порт сервера',
  },
  es: {
    // App
    appTitle: 'KiroaaS',
    dashboard: 'Panel',

    // Tabs
    tabSettings: 'Configuración',
    tabLogs: 'Registros',

    // Server Control
    serverControl: 'Control del servidor',
    serverControlDesc: 'Administra el servidor de KiroaaS',
    startServer: 'Iniciar servidor',
    stopServer: 'Detener servidor',
    starting: 'Iniciando...',
    stopping: 'Deteniendo...',
    runningOnPort: 'Ejecutándose en el puerto',
    configureApiKeyFirst:
      'Configura tu clave API en la pestaña Configuración antes de iniciar el servidor.',
    startServerFailed: 'No se pudo iniciar el servidor',
    stopServerFailed: 'No se pudo detener el servidor',

    // Status
    statusStopped: 'Detenido',
    statusStarting: 'Iniciando',
    statusRunning: 'En ejecución',
    statusError: 'Error',

    // Settings Form
    authSettings: 'Autenticación',
    authMethod: 'Método de autenticación',
    authRefreshToken: 'Token de actualización',
    authCredsFile: 'Archivo de credenciales',
    authCliDb: 'Base de datos de Kiro CLI',
    refreshToken: 'Token de actualización',
    refreshTokenPlaceholder: 'Introduce tu token de actualización',
    credsFilePath: 'Ruta del archivo de credenciales',
    cliDbPath: 'Ruta de la base de datos de Kiro CLI',

    securitySettings: 'Seguridad',
    proxyApiKey: 'Clave API del proxy',
    proxyApiKeyPlaceholder: 'Tu clave súper secreta',
    proxyApiKeyDesc: 'Esta clave es necesaria para acceder a la API del gateway',
    generate: 'Generar',
    generateApiKey: 'Generar clave API aleatoria',

    serverSettings: 'Servidor',
    host: 'Host',
    port: 'Puerto',
    region: 'Región',
    regionUsEast: 'EE. UU. Este (N. Virginia)',
    regionUsWest: 'EE. UU. Oeste (Oregón)',
    regionEuWest: 'UE (Irlanda)',
    regionApSoutheast: 'Asia-Pacífico (Singapur)',

    saveSettings: 'Guardar configuración',
    saving: 'Guardando...',
    saveSuccess: '¡Configuración guardada correctamente!',
    saveFailed: 'No se pudo guardar la configuración',

    // Credential scanning
    scanCredentials: 'Escanear credenciales',
    scanningCredentials: 'Escaneando...',
    foundCredentials: 'Se encontraron {count} archivo(s) de credenciales',
    noCredentialsFound: 'No se encontraron archivos de credenciales',
    selectCredential: 'Seleccionar archivo de credenciales',
    scanFailed: 'Falló el escaneo',
    credentialsFound: 'Credenciales detectadas',
    autoDetectedCredentials:
      'Detectamos automáticamente las siguientes credenciales en tu sistema:',
    useRecommended: 'Usar recomendado',
    dismiss: 'Descartar',
    confirm: 'Confirmar',
    found: 'encontrados',

    // Advanced Settings
    advancedSettings: 'Configuración avanzada',
    vpnProxy: 'VPN/Proxy',
    vpnProxyUrl: 'URL del proxy VPN',
    vpnProxyUrlPlaceholder: 'http://proxy.example.com:8080',
    vpnProxyUrlDesc: 'Servidor proxy opcional para conexiones VPN',

    timeoutSettings: 'Tiempos de espera',
    firstTokenTimeout: 'Tiempo de espera del primer token (segundos)',
    streamingReadTimeout: 'Tiempo de espera de lectura de streaming (segundos)',

    featureSettings: 'Funciones',
    enableFakeReasoning: 'Habilitar razonamiento simulado',
    maxTokens: 'Máx. tokens',
    enableTruncationRecovery: 'Habilitar recuperación por truncamiento',

    logSettings: 'Registro',
    logLevel: 'Nivel de registro',
    logDebug: 'Depurar',
    logInfo: 'Información',
    logWarning: 'Advertencia',
    logError: 'Error',
    debugMode: 'Modo de depuración',
    debugOff: 'Desactivado',
    debugOn: 'Activado',
    debugVerbose: 'Detallado',

    // Log Viewer
    serverLogs: 'Registros del servidor',
    autoScroll: 'Desplazamiento automático',
    export: 'Exportar',
    clear: 'Limpiar',
    noLogs: 'Aún no hay registros. Inicia el servidor para verlos.',

    // Footer
    reportIssue: 'Reportar un problema',

    // Errors
    configError: 'Error de configuración',
    loadingConfig: 'Cargando configuración...',
    retry: 'Reintentar',

    // Language
    language: 'Idioma',

    // Dashboard
    operations: 'Operaciones',
    systemLogs: 'Registros del sistema',
    configurationError: 'Error de configuración',
    dashboardDesc: 'Administra tu gateway y el estado de conexión aquí.',
    settingsDesc: 'Configura la autenticación y el proxy.',
    logsDesc: 'Actividad del servidor en tiempo real.',
    gatewayStatus: 'ESTADO DEL GATEWAY',
    active: 'Activo',
    offline: 'Sin conexión',
    online: 'EN LÍNEA',
    stopped: 'DETENIDO',
    servingOnPort: 'Atendiendo solicitudes en el puerto {port}',
    readyToInitialize: 'Listo para inicializar la conexión',
    listeningPort: 'Puerto de escucha',
    auth: 'Autenticación',
    auto: 'AUTO',
    liveActivity: 'Actividad en vivo',
    expand: 'Expandir',
    waitingForEvents: 'Esperando eventos del servidor...',
    advanced: 'Avanzado',
    proTip: 'Consejo',
    proTipDesc:
      'Si no tienes una clave API del proxy proporcionada por tu administrador, usa el botón "Generar" para crear una clave segura.',
    administrator: 'Administrador',

    // API Examples
    apiExamples: 'Ejemplos de API',
    copy: 'Copiar',
    copied: 'Copiado',

    // Chat
    tabChat: 'Chat',
    chatDesc: 'Chatea con modelos de IA.',
    chatWelcome: 'Iniciar conversación',
    chatWelcomeDesc: 'Envía un mensaje para empezar a chatear con IA',
    chatPlaceholder: 'Escribe un mensaje...',
    chatServerOffline: 'Servidor desconectado',
    chatServerOfflineDesc: 'Por favor, inicia el servidor primero',
    chatError: 'Error al enviar mensaje',

    // CC Switch Import
    ccSwitchImport: 'Importar a CC Switch',
    ccSwitchIntro: 'CC Switch es un gestor de configuración de Claude Code que permite cambiar rápidamente entre diferentes proveedores de API.',
    ccSwitchImportDesc: 'Importa esta configuración a CC Switch con un clic para que Claude Code use el gateway de KiroaaS.',
    importToCCSwitch: 'Importar a CC Switch',
    importing: 'Importando...',
    importSuccess: 'Importación exitosa',
    notConfigured: 'No configurado',

    // Settings Form
    authenticationMethod: 'Método de autenticación',
    howGatewayConnects: 'Cómo el gateway se conecta a los servicios de Kiro.',
    sqliteDatabasePath: 'Ruta de la base de datos SQLite',
    credentialsFilePath: 'Ruta del archivo de credenciales',
    security: 'Seguridad',
    protectEndpoint: 'Protege el endpoint de tu gateway.',
    hide: 'Ocultar',
    show: 'Mostrar',
    realValue: 'Valor real',
    clientsIncludeKey:
      'Los clientes (como Cursor o VS Code) deben incluir esta clave en el encabezado Authorization.',
    savedSuccessfully: 'Guardado correctamente',
    savingChanges: 'Guardando cambios...',
    saveConfiguration: 'Guardar configuración',

    // Log Viewer
    systemOutput: 'Salida del sistema',
    eventsCaptured: '{count} eventos capturados',
    live: 'En vivo',
    paused: 'Pausado',
    noLogsAvailable: 'No hay registros para mostrar',
    resumeFeed: 'Reanudar feed',

    // Advanced Settings
    vpnProxyTunnel: 'Túnel VPN / Proxy',
    timeoutsSeconds: 'Tiempos de espera (segundos)',
    firstToken: 'Primer token',
    streamRead: 'Lectura de stream',
    serverPort: 'Puerto del servidor',
  },
  id: {
    // App
    appTitle: 'KiroaaS',
    dashboard: 'Dasbor',

    // Tabs
    tabSettings: 'Pengaturan',
    tabLogs: 'Log',

    // Server Control
    serverControl: 'Kontrol Server',
    serverControlDesc: 'Kelola server KiroaaS',
    startServer: 'Mulai Server',
    stopServer: 'Hentikan Server',
    starting: 'Memulai...',
    stopping: 'Menghentikan...',
    runningOnPort: 'Berjalan di port',
    configureApiKeyFirst:
      'Silakan konfigurasikan kunci API Anda di tab Pengaturan sebelum memulai server.',
    startServerFailed: 'Gagal memulai server',
    stopServerFailed: 'Gagal menghentikan server',

    // Status
    statusStopped: 'Berhenti',
    statusStarting: 'Memulai',
    statusRunning: 'Berjalan',
    statusError: 'Kesalahan',

    // Settings Form
    authSettings: 'Autentikasi',
    authMethod: 'Metode Autentikasi',
    authRefreshToken: 'Refresh Token',
    authCredsFile: 'File Kredensial',
    authCliDb: 'Database Kiro CLI',
    refreshToken: 'Refresh Token',
    refreshTokenPlaceholder: 'Masukkan refresh token Anda',
    credsFilePath: 'Path File Kredensial',
    cliDbPath: 'Path Database Kiro CLI',

    securitySettings: 'Keamanan',
    proxyApiKey: 'Kunci API Proxy',
    proxyApiKeyPlaceholder: 'Kunci super rahasia Anda',
    proxyApiKeyDesc: 'Kunci ini diperlukan untuk mengakses API gateway',
    generate: 'Buat',
    generateApiKey: 'Buat kunci API acak',

    serverSettings: 'Server',
    host: 'Host',
    port: 'Port',
    region: 'Wilayah',
    regionUsEast: 'AS Timur (N. Virginia)',
    regionUsWest: 'AS Barat (Oregon)',
    regionEuWest: 'UE (Irlandia)',
    regionApSoutheast: 'Asia Pasifik (Singapura)',

    saveSettings: 'Simpan Pengaturan',
    saving: 'Menyimpan...',
    saveSuccess: 'Pengaturan berhasil disimpan!',
    saveFailed: 'Gagal menyimpan pengaturan',

    // Credential scanning
    scanCredentials: 'Pindai Kredensial',
    scanningCredentials: 'Memindai...',
    foundCredentials: 'Menemukan {count} file kredensial',
    noCredentialsFound: 'Tidak ada file kredensial ditemukan',
    selectCredential: 'Pilih File Kredensial',
    scanFailed: 'Pemindaian gagal',
    credentialsFound: 'Kredensial Terdeteksi',
    autoDetectedCredentials:
      'Kami mendeteksi kredensial berikut secara otomatis di sistem Anda:',
    useRecommended: 'Gunakan Rekomendasi',
    dismiss: 'Abaikan',
    confirm: 'Konfirmasi',
    found: 'ditemukan',

    // Advanced Settings
    advancedSettings: 'Pengaturan Lanjutan',
    vpnProxy: 'VPN/Proxy',
    vpnProxyUrl: 'URL Proxy VPN',
    vpnProxyUrlPlaceholder: 'http://proxy.example.com:8080',
    vpnProxyUrlDesc: 'Server proxy opsional untuk koneksi VPN',

    timeoutSettings: 'Timeout',
    firstTokenTimeout: 'Timeout Token Pertama (detik)',
    streamingReadTimeout: 'Timeout Baca Streaming (detik)',

    featureSettings: 'Fitur',
    enableFakeReasoning: 'Aktifkan Penalaran Palsu',
    maxTokens: 'Token Maks',
    enableTruncationRecovery: 'Aktifkan Pemulihan Trunkasi',

    logSettings: 'Logging',
    logLevel: 'Level Log',
    logDebug: 'DEBUG',
    logInfo: 'INFO',
    logWarning: 'PERINGATAN',
    logError: 'ERROR',
    debugMode: 'Mode Debug',
    debugOff: 'Mati',
    debugOn: 'Nyala',
    debugVerbose: 'Rinci',

    // Log Viewer
    serverLogs: 'Log Server',
    autoScroll: 'Gulir otomatis',
    export: 'Ekspor',
    clear: 'Bersihkan',
    noLogs: 'Belum ada log. Mulai server untuk melihat log.',

    // Footer
    reportIssue: 'Laporkan Masalah',

    // Errors
    configError: 'Kesalahan Konfigurasi',
    loadingConfig: 'Memuat konfigurasi...',
    retry: 'Coba lagi',

    // Language
    language: 'Bahasa',

    // Dashboard
    operations: 'Operasional',
    systemLogs: 'Log Sistem',
    configurationError: 'Kesalahan Konfigurasi',
    dashboardDesc: 'Kelola gateway dan status koneksi Anda di sini.',
    settingsDesc: 'Konfigurasi autentikasi dan pengaturan proxy.',
    logsDesc: 'Aktivitas server real-time.',
    gatewayStatus: 'STATUS GATEWAY',
    active: 'Aktif',
    offline: 'Offline',
    online: 'ONLINE',
    stopped: 'BERHENTI',
    servingOnPort: 'Melayani permintaan di port {port}',
    readyToInitialize: 'Siap menginisialisasi koneksi',
    listeningPort: 'Port yang didengarkan',
    auth: 'Autentikasi',
    auto: 'OTOMATIS',
    liveActivity: 'Aktivitas Langsung',
    expand: 'Perluas',
    waitingForEvents: 'Menunggu event server...',
    advanced: 'Lanjutan',
    proTip: 'Tips',
    proTipDesc:
      'Jika Anda tidak memiliki Kunci API Proxy dari administrator, gunakan tombol "Buat" untuk membuat kunci yang aman.',
    administrator: 'Administrator',

    // API Examples
    apiExamples: 'Contoh API',
    copy: 'Salin',
    copied: 'Disalin',

    // Chat
    tabChat: 'Obrolan',
    chatDesc: 'Ngobrol dengan model AI.',
    chatWelcome: 'Mulai percakapan',
    chatWelcomeDesc: 'Kirim pesan untuk mulai mengobrol dengan AI',
    chatPlaceholder: 'Ketik pesan...',
    chatServerOffline: 'Server offline',
    chatServerOfflineDesc: 'Silakan mulai server terlebih dahulu',
    chatError: 'Gagal mengirim pesan',

    // CC Switch Import
    ccSwitchImport: 'Impor ke CC Switch',
    ccSwitchIntro: 'CC Switch adalah pengelola konfigurasi Claude Code yang memungkinkan perpindahan cepat antara berbagai API Provider.',
    ccSwitchImportDesc: 'Impor konfigurasi ini ke CC Switch dengan satu klik agar Claude Code menggunakan gateway KiroaaS.',
    importToCCSwitch: 'Impor ke CC Switch',
    importing: 'Mengimpor...',
    importSuccess: 'Impor berhasil',
    notConfigured: 'Belum dikonfigurasi',

    // Settings Form
    authenticationMethod: 'Metode Autentikasi',
    howGatewayConnects: 'Bagaimana gateway terhubung ke layanan Kiro.',
    sqliteDatabasePath: 'Path Database SQLite',
    credentialsFilePath: 'Path File Kredensial',
    security: 'Keamanan',
    protectEndpoint: 'Lindungi endpoint gateway Anda.',
    hide: 'Sembunyikan',
    show: 'Tampilkan',
    realValue: 'Nilai asli',
    clientsIncludeKey:
      'Klien (seperti Cursor atau VS Code) harus menyertakan kunci ini di header Authorization.',
    savedSuccessfully: 'Berhasil disimpan',
    savingChanges: 'Menyimpan perubahan...',
    saveConfiguration: 'Simpan Konfigurasi',

    // Log Viewer
    systemOutput: 'Output Sistem',
    eventsCaptured: '{count} event tertangkap',
    live: 'Langsung',
    paused: 'Dijeda',
    noLogsAvailable: 'Tidak ada log untuk ditampilkan',
    resumeFeed: 'Lanjutkan Feed',

    // Advanced Settings
    vpnProxyTunnel: 'Terowongan VPN / Proxy',
    timeoutsSeconds: 'Timeout (detik)',
    firstToken: 'Token pertama',
    streamRead: 'Baca stream',
    serverPort: 'Port server',
  },
  pt: {
    // App
    appTitle: 'KiroaaS',
    dashboard: 'Painel',

    // Tabs
    tabSettings: 'Configurações',
    tabLogs: 'Logs',

    // Server Control
    serverControl: 'Controle do servidor',
    serverControlDesc: 'Gerencie o servidor KiroaaS',
    startServer: 'Iniciar servidor',
    stopServer: 'Parar servidor',
    starting: 'Iniciando...',
    stopping: 'Parando...',
    runningOnPort: 'Executando na porta',
    configureApiKeyFirst:
      'Configure sua chave de API na aba Configurações antes de iniciar o servidor.',
    startServerFailed: 'Falha ao iniciar o servidor',
    stopServerFailed: 'Falha ao parar o servidor',

    // Status
    statusStopped: 'Parado',
    statusStarting: 'Iniciando',
    statusRunning: 'Em execução',
    statusError: 'Erro',

    // Settings Form
    authSettings: 'Autenticação',
    authMethod: 'Método de autenticação',
    authRefreshToken: 'Token de atualização',
    authCredsFile: 'Arquivo de credenciais',
    authCliDb: 'Banco de dados do Kiro CLI',
    refreshToken: 'Token de atualização',
    refreshTokenPlaceholder: 'Digite seu token de atualização',
    credsFilePath: 'Caminho do arquivo de credenciais',
    cliDbPath: 'Caminho do banco de dados do Kiro CLI',

    securitySettings: 'Segurança',
    proxyApiKey: 'Chave de API do proxy',
    proxyApiKeyPlaceholder: 'Sua chave supersecreta',
    proxyApiKeyDesc: 'Esta chave é necessária para acessar a API do gateway',
    generate: 'Gerar',
    generateApiKey: 'Gerar chave de API aleatória',

    serverSettings: 'Servidor',
    host: 'Host',
    port: 'Porta',
    region: 'Região',
    regionUsEast: 'EUA Leste (N. Virginia)',
    regionUsWest: 'EUA Oeste (Oregon)',
    regionEuWest: 'UE (Irlanda)',
    regionApSoutheast: 'Ásia-Pacífico (Singapura)',

    saveSettings: 'Salvar configurações',
    saving: 'Salvando...',
    saveSuccess: 'Configurações salvas com sucesso!',
    saveFailed: 'Falha ao salvar configurações',

    // Credential scanning
    scanCredentials: 'Buscar credenciais',
    scanningCredentials: 'Buscando...',
    foundCredentials: '{count} arquivo(s) de credenciais encontrado(s)',
    noCredentialsFound: 'Nenhum arquivo de credenciais encontrado',
    selectCredential: 'Selecionar arquivo de credenciais',
    scanFailed: 'Falha na busca',
    credentialsFound: 'Credenciais detectadas',
    autoDetectedCredentials:
      'Detectamos automaticamente as seguintes credenciais no seu sistema:',
    useRecommended: 'Usar recomendado',
    dismiss: 'Ignorar',
    confirm: 'Confirmar',
    found: 'encontrado(s)',

    // Advanced Settings
    advancedSettings: 'Configurações avançadas',
    vpnProxy: 'VPN/Proxy',
    vpnProxyUrl: 'URL do proxy VPN',
    vpnProxyUrlPlaceholder: 'http://proxy.example.com:8080',
    vpnProxyUrlDesc: 'Servidor proxy opcional para conexões VPN',

    timeoutSettings: 'Timeouts',
    firstTokenTimeout: 'Timeout do primeiro token (segundos)',
    streamingReadTimeout: 'Timeout de leitura do streaming (segundos)',

    featureSettings: 'Recursos',
    enableFakeReasoning: 'Ativar raciocínio simulado',
    maxTokens: 'Máx. de tokens',
    enableTruncationRecovery: 'Ativar recuperação de truncamento',

    logSettings: 'Logs',
    logLevel: 'Nível de log',
    logDebug: 'DEBUG',
    logInfo: 'INFO',
    logWarning: 'AVISO',
    logError: 'ERRO',
    debugMode: 'Modo de depuração',
    debugOff: 'Desligado',
    debugOn: 'Ligado',
    debugVerbose: 'Detalhado',

    // Log Viewer
    serverLogs: 'Logs do servidor',
    autoScroll: 'Rolagem automática',
    export: 'Exportar',
    clear: 'Limpar',
    noLogs: 'Ainda não há logs. Inicie o servidor para vê-los.',

    // Footer
    reportIssue: 'Reportar problema',

    // Errors
    configError: 'Erro de configuração',
    loadingConfig: 'Carregando configuração...',
    retry: 'Tentar novamente',

    // Language
    language: 'Idioma',

    // Dashboard
    operations: 'Operações',
    systemLogs: 'Logs do sistema',
    configurationError: 'Erro de configuração',
    dashboardDesc: 'Gerencie seu gateway e o status da conexão aqui.',
    settingsDesc: 'Configure autenticação e proxy.',
    logsDesc: 'Atividade do servidor em tempo real.',
    gatewayStatus: 'STATUS DO GATEWAY',
    active: 'Ativo',
    offline: 'Offline',
    online: 'ONLINE',
    stopped: 'PARADO',
    servingOnPort: 'Atendendo requisições na porta {port}',
    readyToInitialize: 'Pronto para inicializar a conexão',
    listeningPort: 'Porta de escuta',
    auth: 'Autenticação',
    auto: 'AUTO',
    liveActivity: 'Atividade ao vivo',
    expand: 'Expandir',
    waitingForEvents: 'Aguardando eventos do servidor...',
    advanced: 'Avançado',
    proTip: 'Dica',
    proTipDesc:
      'Se você não tem uma chave de API do proxy fornecida pelo administrador, use o botão "Gerar" para criar uma chave segura.',
    administrator: 'Administrador',

    // API Examples
    apiExamples: 'Exemplos de API',
    copy: 'Copiar',
    copied: 'Copiado',

    // Chat
    tabChat: 'Chat',
    chatDesc: 'Converse com modelos de IA.',
    chatWelcome: 'Iniciar conversa',
    chatWelcomeDesc: 'Envie uma mensagem para começar a conversar com IA',
    chatPlaceholder: 'Digite uma mensagem...',
    chatServerOffline: 'Servidor offline',
    chatServerOfflineDesc: 'Por favor, inicie o servidor primeiro',
    chatError: 'Falha ao enviar mensagem',

    // CC Switch Import
    ccSwitchImport: 'Importar para CC Switch',
    ccSwitchIntro: 'CC Switch é um gerenciador de configuração do Claude Code que permite alternar rapidamente entre diferentes provedores de API.',
    ccSwitchImportDesc: 'Importe esta configuração para o CC Switch com um clique para que o Claude Code use o gateway KiroaaS.',
    importToCCSwitch: 'Importar para CC Switch',
    importing: 'Importando...',
    importSuccess: 'Importação bem-sucedida',
    notConfigured: 'Não configurado',

    // Settings Form
    authenticationMethod: 'Método de autenticação',
    howGatewayConnects: 'Como o gateway se conecta aos serviços Kiro.',
    sqliteDatabasePath: 'Caminho do banco de dados SQLite',
    credentialsFilePath: 'Caminho do arquivo de credenciais',
    security: 'Segurança',
    protectEndpoint: 'Proteja o endpoint do seu gateway.',
    hide: 'Ocultar',
    show: 'Mostrar',
    realValue: 'Valor real',
    clientsIncludeKey:
      'Clientes (como Cursor ou VS Code) devem incluir esta chave no cabeçalho Authorization.',
    savedSuccessfully: 'Salvo com sucesso',
    savingChanges: 'Salvando alterações...',
    saveConfiguration: 'Salvar configuração',

    // Log Viewer
    systemOutput: 'Saída do sistema',
    eventsCaptured: '{count} evento(s) capturado(s)',
    live: 'Ao vivo',
    paused: 'Pausado',
    noLogsAvailable: 'Nenhum log disponível para exibir',
    resumeFeed: 'Retomar feed',

    // Advanced Settings
    vpnProxyTunnel: 'Túnel VPN / Proxy',
    timeoutsSeconds: 'Timeouts (segundos)',
    firstToken: 'Primeiro token',
    streamRead: 'Leitura do stream',
    serverPort: 'Porta do servidor',
  },
  ja: {
    // App
    appTitle: 'KiroaaS',
    dashboard: 'ダッシュボード',

    // Tabs
    tabSettings: '設定',
    tabLogs: 'ログ',

    // Server Control
    serverControl: 'サーバー制御',
    serverControlDesc: 'KiroaaS サーバーを管理します',
    startServer: 'サーバーを起動',
    stopServer: 'サーバーを停止',
    starting: '起動中...',
    stopping: '停止中...',
    runningOnPort: 'ポート',
    configureApiKeyFirst:
      'サーバーを起動する前に、設定タブで API キーを設定してください。',
    startServerFailed: 'サーバーの起動に失敗しました',
    stopServerFailed: 'サーバーの停止に失敗しました',

    // Status
    statusStopped: '停止',
    statusStarting: '起動中',
    statusRunning: '稼働中',
    statusError: 'エラー',

    // Settings Form
    authSettings: '認証',
    authMethod: '認証方式',
    authRefreshToken: 'リフレッシュトークン',
    authCredsFile: '資格情報ファイル',
    authCliDb: 'Kiro CLI データベース',
    refreshToken: 'リフレッシュトークン',
    refreshTokenPlaceholder: 'リフレッシュトークンを入力',
    credsFilePath: '資格情報ファイルのパス',
    cliDbPath: 'Kiro CLI データベースのパス',

    securitySettings: 'セキュリティ',
    proxyApiKey: 'プロキシ API キー',
    proxyApiKeyPlaceholder: '超秘密キー',
    proxyApiKeyDesc: 'ゲートウェイ API にアクセスするために必要です',
    generate: '生成',
    generateApiKey: 'ランダムな API キーを生成',

    serverSettings: 'サーバー',
    host: 'ホスト',
    port: 'ポート',
    region: 'リージョン',
    regionUsEast: '米国東部 (バージニア北部)',
    regionUsWest: '米国西部 (オレゴン)',
    regionEuWest: '欧州 (アイルランド)',
    regionApSoutheast: 'アジア太平洋 (シンガポール)',

    saveSettings: '設定を保存',
    saving: '保存中...',
    saveSuccess: '設定を保存しました！',
    saveFailed: '設定の保存に失敗しました',

    // Credential scanning
    scanCredentials: '資格情報をスキャン',
    scanningCredentials: 'スキャン中...',
    foundCredentials: '資格情報ファイルを {count} 件見つけました',
    noCredentialsFound: '資格情報ファイルが見つかりません',
    selectCredential: '資格情報ファイルを選択',
    scanFailed: 'スキャンに失敗しました',
    credentialsFound: '資格情報を検出しました',
    autoDetectedCredentials:
      'システム内で次の資格情報を自動検出しました:',
    useRecommended: '推奨を使用',
    dismiss: '無視',
    confirm: '確認',
    found: '件',

    // Advanced Settings
    advancedSettings: '高度な設定',
    vpnProxy: 'VPN/プロキシ',
    vpnProxyUrl: 'VPN プロキシ URL',
    vpnProxyUrlPlaceholder: 'http://proxy.example.com:8080',
    vpnProxyUrlDesc: 'VPN 接続用の任意のプロキシサーバー',

    timeoutSettings: 'タイムアウト',
    firstTokenTimeout: '最初のトークンのタイムアウト (秒)',
    streamingReadTimeout: 'ストリーミング読み取りタイムアウト (秒)',

    featureSettings: '機能',
    enableFakeReasoning: '疑似推論を有効化',
    maxTokens: '最大トークン数',
    enableTruncationRecovery: '切り詰め復旧を有効化',

    logSettings: 'ログ',
    logLevel: 'ログレベル',
    logDebug: 'デバッグ',
    logInfo: '情報',
    logWarning: '警告',
    logError: 'エラー',
    debugMode: 'デバッグモード',
    debugOff: 'オフ',
    debugOn: 'オン',
    debugVerbose: '詳細',

    // Log Viewer
    serverLogs: 'サーバーログ',
    autoScroll: '自動スクロール',
    export: 'エクスポート',
    clear: 'クリア',
    noLogs: 'ログはまだありません。サーバーを起動すると表示されます。',

    // Footer
    reportIssue: '問題を報告',

    // Errors
    configError: '設定エラー',
    loadingConfig: '設定を読み込み中...',
    retry: '再試行',

    // Language
    language: '言語',

    // Dashboard
    operations: '運用',
    systemLogs: 'システムログ',
    configurationError: '設定エラー',
    dashboardDesc: 'ここでゲートウェイと接続状態を管理します。',
    settingsDesc: '認証とプロキシ設定を構成します。',
    logsDesc: 'リアルタイムのサーバーアクティビティ。',
    gatewayStatus: 'ゲートウェイ状態',
    active: '稼働',
    offline: 'オフライン',
    online: 'ONLINE',
    stopped: 'STOPPED',
    servingOnPort: 'ポート {port} でリクエストを処理中',
    readyToInitialize: '接続初期化の準備完了',
    listeningPort: '待受ポート',
    auth: '認証',
    auto: '自動',
    liveActivity: 'ライブアクティビティ',
    expand: '展開',
    waitingForEvents: 'サーバーイベントを待機中...',
    advanced: '高度',
    proTip: 'ヒント',
    proTipDesc:
      '管理者からプロキシ API キーが提供されていない場合は、「生成」ボタンで安全なキーを作成してください。',
    administrator: '管理者',

    // API Examples
    apiExamples: 'API サンプル',
    copy: 'コピー',
    copied: 'コピーしました',

    // Chat
    tabChat: 'チャット',
    chatDesc: 'AIモデルとチャットします。',
    chatWelcome: '会話を始める',
    chatWelcomeDesc: 'メッセージを送信してAIとのチャットを開始',
    chatPlaceholder: 'メッセージを入力...',
    chatServerOffline: 'サーバーオフライン',
    chatServerOfflineDesc: '先にサーバーを起動してください',
    chatError: 'メッセージの送信に失敗しました',

    // CC Switch Import
    ccSwitchImport: 'CC Switch にインポート',
    ccSwitchIntro: 'CC Switch は Claude Code の設定マネージャーで、異なる API プロバイダー間を素早く切り替えることができます。',
    ccSwitchImportDesc: 'ワンクリックでこの設定を CC Switch にインポートし、Claude Code が KiroaaS ゲートウェイを使用できるようにします。',
    importToCCSwitch: 'CC Switch にインポート',
    importing: 'インポート中...',
    importSuccess: 'インポート成功',
    notConfigured: '未設定',

    // Settings Form
    authenticationMethod: '認証方式',
    howGatewayConnects: 'ゲートウェイが Kiro サービスに接続する方法。',
    sqliteDatabasePath: 'SQLite データベースのパス',
    credentialsFilePath: '資格情報ファイルのパス',
    security: 'セキュリティ',
    protectEndpoint: 'ゲートウェイのエンドポイントを保護します。',
    hide: '非表示',
    show: '表示',
    realValue: '実際の値',
    clientsIncludeKey:
      'クライアント (Cursor や VS Code など) は Authorization ヘッダーにこのキーを含める必要があります。',
    savedSuccessfully: '保存しました',
    savingChanges: '保存中...',
    saveConfiguration: '設定を保存',

    // Log Viewer
    systemOutput: 'システム出力',
    eventsCaptured: '{count} 件のイベントを取得',
    live: 'ライブ',
    paused: '一時停止',
    noLogsAvailable: '表示できるログがありません',
    resumeFeed: 'フィードを再開',

    // Advanced Settings
    vpnProxyTunnel: 'VPN / プロキシトンネル',
    timeoutsSeconds: 'タイムアウト (秒)',
    firstToken: '最初のトークン',
    streamRead: 'ストリーム読み取り',
    serverPort: 'サーバーポート',
  },
  ko: {
    // App
    appTitle: 'KiroaaS',
    dashboard: '대시보드',

    // Tabs
    tabSettings: '설정',
    tabLogs: '로그',

    // Server Control
    serverControl: '서버 제어',
    serverControlDesc: 'KiroaaS 서버를 관리합니다',
    startServer: '서버 시작',
    stopServer: '서버 중지',
    starting: '시작 중...',
    stopping: '중지 중...',
    runningOnPort: '포트',
    configureApiKeyFirst:
      '서버를 시작하기 전에 설정 탭에서 API 키를 먼저 구성하세요.',
    startServerFailed: '서버 시작 실패',
    stopServerFailed: '서버 중지 실패',

    // Status
    statusStopped: '중지됨',
    statusStarting: '시작 중',
    statusRunning: '실행 중',
    statusError: '오류',

    // Settings Form
    authSettings: '인증',
    authMethod: '인증 방식',
    authRefreshToken: '리프레시 토큰',
    authCredsFile: '자격 증명 파일',
    authCliDb: 'Kiro CLI 데이터베이스',
    refreshToken: '리프레시 토큰',
    refreshTokenPlaceholder: '리프레시 토큰을 입력하세요',
    credsFilePath: '자격 증명 파일 경로',
    cliDbPath: 'Kiro CLI DB 경로',

    securitySettings: '보안',
    proxyApiKey: '프록시 API 키',
    proxyApiKeyPlaceholder: '아주 비밀스러운 키',
    proxyApiKeyDesc: '게이트웨이 API에 접근하려면 이 키가 필요합니다',
    generate: '생성',
    generateApiKey: '무작위 API 키 생성',

    serverSettings: '서버',
    host: '호스트',
    port: '포트',
    region: '리전',
    regionUsEast: '미국 동부(버지니아 북부)',
    regionUsWest: '미국 서부(오리건)',
    regionEuWest: '유럽(아일랜드)',
    regionApSoutheast: '아시아 태평양(싱가포르)',

    saveSettings: '설정 저장',
    saving: '저장 중...',
    saveSuccess: '설정이 저장되었습니다!',
    saveFailed: '설정 저장 실패',

    // Credential scanning
    scanCredentials: '자격 증명 스캔',
    scanningCredentials: '스캔 중...',
    foundCredentials: '자격 증명 파일 {count}개를 찾았습니다',
    noCredentialsFound: '자격 증명 파일을 찾지 못했습니다',
    selectCredential: '자격 증명 파일 선택',
    scanFailed: '스캔 실패',
    credentialsFound: '자격 증명 감지됨',
    autoDetectedCredentials:
      '시스템에서 다음 자격 증명을 자동으로 감지했습니다:',
    useRecommended: '권장 설정 사용',
    dismiss: '무시',
    confirm: '확인',
    found: '개',

    // Advanced Settings
    advancedSettings: '고급 설정',
    vpnProxy: 'VPN/프록시',
    vpnProxyUrl: 'VPN 프록시 URL',
    vpnProxyUrlPlaceholder: 'http://proxy.example.com:8080',
    vpnProxyUrlDesc: 'VPN 연결을 위한 선택적 프록시 서버',

    timeoutSettings: '타임아웃',
    firstTokenTimeout: '첫 토큰 타임아웃(초)',
    streamingReadTimeout: '스트리밍 읽기 타임아웃(초)',

    featureSettings: '기능',
    enableFakeReasoning: '가짜 추론 사용',
    maxTokens: '최대 토큰',
    enableTruncationRecovery: '잘림 복구 사용',

    logSettings: '로깅',
    logLevel: '로그 레벨',
    logDebug: '디버그',
    logInfo: '정보',
    logWarning: '경고',
    logError: '오류',
    debugMode: '디버그 모드',
    debugOff: '꺼짐',
    debugOn: '켜짐',
    debugVerbose: '자세히',

    // Log Viewer
    serverLogs: '서버 로그',
    autoScroll: '자동 스크롤',
    export: '내보내기',
    clear: '지우기',
    noLogs: '아직 로그가 없습니다. 서버를 시작하면 표시됩니다.',

    // Footer
    reportIssue: '문제 신고',

    // Errors
    configError: '구성 오류',
    loadingConfig: '구성을 불러오는 중...',
    retry: '재시도',

    // Language
    language: '언어',

    // Dashboard
    operations: '운영',
    systemLogs: '시스템 로그',
    configurationError: '구성 오류',
    dashboardDesc: '여기에서 게이트웨이와 연결 상태를 관리합니다.',
    settingsDesc: '인증 및 프록시 설정을 구성합니다.',
    logsDesc: '실시간 서버 활동 스트리밍.',
    gatewayStatus: '게이트웨이 상태',
    active: '활성',
    offline: '오프라인',
    online: 'ONLINE',
    stopped: 'STOPPED',
    servingOnPort: '포트 {port}에서 요청 처리 중',
    readyToInitialize: '연결 초기화 준비 완료',
    listeningPort: '수신 포트',
    auth: '인증',
    auto: '자동',
    liveActivity: '실시간 활동',
    expand: '확장',
    waitingForEvents: '서버 이벤트를 기다리는 중...',
    advanced: '고급',
    proTip: '팁',
    proTipDesc:
      '관리자가 제공한 프록시 API 키가 없다면 "생성" 버튼으로 안전한 키를 만드세요.',
    administrator: '관리자',

    // API Examples
    apiExamples: 'API 예제',
    copy: '복사',
    copied: '복사됨',

    // Chat
    tabChat: '채팅',
    chatDesc: 'AI 모델과 대화합니다.',
    chatWelcome: '대화 시작',
    chatWelcomeDesc: '메시지를 보내 AI와 채팅을 시작하세요',
    chatPlaceholder: '메시지 입력...',
    chatServerOffline: '서버 오프라인',
    chatServerOfflineDesc: '먼저 서버를 시작하세요',
    chatError: '메시지 전송 실패',

    // CC Switch Import
    ccSwitchImport: 'CC Switch로 가져오기',
    ccSwitchIntro: 'CC Switch는 다양한 API Provider 간에 빠르게 전환할 수 있는 Claude Code 구성 관리자입니다.',
    ccSwitchImportDesc: '이 구성을 CC Switch로 원클릭 가져오기하여 Claude Code가 KiroaaS 게이트웨이를 사용하도록 합니다.',
    importToCCSwitch: 'CC Switch로 가져오기',
    importing: '가져오는 중...',
    importSuccess: '가져오기 성공',
    notConfigured: '구성되지 않음',

    // Settings Form
    authenticationMethod: '인증 방식',
    howGatewayConnects: '게이트웨이가 Kiro 서비스에 연결하는 방식.',
    sqliteDatabasePath: 'SQLite DB 경로',
    credentialsFilePath: '자격 증명 파일 경로',
    security: '보안',
    protectEndpoint: '게이트웨이 엔드포인트를 보호하세요.',
    hide: '숨기기',
    show: '표시',
    realValue: '실제 값',
    clientsIncludeKey:
      '클라이언트(예: Cursor 또는 VS Code)는 Authorization 헤더에 이 키를 포함해야 합니다.',
    savedSuccessfully: '저장됨',
    savingChanges: '저장 중...',
    saveConfiguration: '구성 저장',

    // Log Viewer
    systemOutput: '시스템 출력',
    eventsCaptured: '이벤트 {count}개 캡처됨',
    live: '실시간',
    paused: '일시 중지',
    noLogsAvailable: '표시할 로그가 없습니다',
    resumeFeed: '피드 재개',

    // Advanced Settings
    vpnProxyTunnel: 'VPN / 프록시 터널',
    timeoutsSeconds: '타임아웃(초)',
    firstToken: '첫 토큰',
    streamRead: '스트림 읽기',
    serverPort: '서버 포트',
  },
};

export type TranslationKey = keyof typeof translations.zh;

export function getTranslation(lang: Language, key: TranslationKey): string {
  return translations[lang]?.[key] || translations.en?.[key] || key;
}
