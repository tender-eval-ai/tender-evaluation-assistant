// The shared demo on Azure (checklist G4): one Container Apps app with three containers
// (web as ingress, the API, the worker), Postgres Flexible Server, an Azure Files share
// for the project files, Azure OpenAI for synthetic projects, and Entra ID sign-in in
// front of all of it. Synthetic data only.
//
// setup.sh creates what this template references but doesn't create (the key vault and
// its secrets, the managed identity that reads them, the sign-in app registration), so
// the identity that deploys this template needs no rights to grant roles.
// deploy.sh runs it. See README.md.

@description('Region for every resource.')
param location string = resourceGroup().location

@description('Short name every resource name starts with.')
@maxLength(10)
param prefix string = 'tender'

@description('Six lowercase letters or digits that make the global names unique (setup.sh chose it).')
@minLength(6)
@maxLength(6)
param suffix string

@description('Container image tag to run (a commit SHA from the deploy workflow).')
param imageTag string

@description('Where the images are: CI pushes backend and web here.')
param registry string = 'ghcr.io/tender-eval-ai/tender-evaluation-assistant'

@description('GitHub user whose read:packages token (key vault secret ghcr-token) pulls the images.')
param ghcrUser string

@description('false for the first pass, which creates everything but the app so the sign-in redirect address can be known.')
param deployApp bool = true

@description('Client id of the Entra app registration for sign-in (setup.sh). Empty means the app gets no public ingress.')
param signInClientId string = ''

@description('A custom domain for the app, such as tender.example.org, bound once by hand with a managed certificate (README: "A custom domain"). Empty: the Azure address only.')
param customDomain string = ''

@description('The managed certificate for customDomain; deploy.sh looks it up. Empty: the domain stays attached without a certificate.')
param customDomainCertificateId string = ''

@description('Region for the Azure OpenAI resource alone, when the main region won\'t deploy the model as openAiSku (setup.sh OPENAI_LOCATION). A region can list a model it then refuses: canadacentral, gpt-4.1-mini GlobalStandard, 2026-09-30.')
param openAiLocation string = location

@description('Azure OpenAI model and version for text and vision. Check what the region offers: az cognitiveservices model list -l <region>.')
param openAiModel string = 'gpt-4.1-mini'
param openAiModelVersion string = '2025-04-14'
@description('Pay-per-token deployment type. Never a provisioned (reserved) one.')
@allowed(['GlobalStandard', 'Standard', 'DataZoneStandard'])
param openAiSku string = 'GlobalStandard'
@description('Thousands of tokens per minute. 10 was too few: four checks at once, each triage call six page images, went past it within a minute (2026-09-30). Pay-per-token, so a higher limit costs nothing idle; the region\'s quota was 200.')
param openAiCapacity int = 100

@description('Where the demo sends anyone who wants to run it on real documents (the UI\'s banner, GET /settings).')
param sourceUrl string = 'https://github.com/tender-eval-ai/tender-evaluation-assistant'

@description('The gateway stops model calls for a project past this many US dollars a day.')
param dailyBudgetUsd string = '2'

@description('MODEL_PRICES JSON (USD per 1M tokens), so the cost ledger prices the Azure model. Without it every call costs $0 and the daily budget never stops anything. The default is gpt-4.1-mini on Global Standard, from the Azure Retail Prices API on 2026-09-30; another OPENAI_MODEL needs its own.')
param modelPricesJson string = '{"gpt-4.1-mini": {"in": 0.40, "cached_in": 0.10, "out": 1.60}}'

var names = {
  identity: '${prefix}-id'
  keyVault: '${prefix}-kv-${suffix}'
  logs: '${prefix}-logs'
  storage: toLower('${prefix}${suffix}data')
  postgres: '${prefix}-pg-${suffix}'
  openAi: '${prefix}-oai-${suffix}'
  environment: '${prefix}-env'
  app: '${prefix}-demo'
}
var pipelines = 'app.checks.vendor_check,app.rulesets.build_job,app.jobs.evaluate_job'

// ------------------------------------------------------------------ made by setup.sh
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: names.identity
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: names.keyVault
}

// ------------------------------------------------------------------ data and models
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: names.logs
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: names.storage
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource files 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

// Project files, OCR cache and the inbox of synthetic cases. Postgres never lives here.
resource dataShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: files
  name: 'data'
  properties: {
    shareQuota: 5
  }
}

module postgres 'postgres.bicep' = {
  name: 'postgres'
  params: {
    location: location
    serverName: names.postgres
    adminLogin: 'tender'
    adminPassword: vault.getSecret('postgres-password')
  }
}

resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: names.openAi
  location: openAiLocation
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: names.openAi
    publicNetworkAccess: 'Enabled'
  }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
  name: openAiModel
  sku: {
    name: openAiSku
    capacity: openAiCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: openAiModel
      version: openAiModelVersion
    }
  }
}

// ------------------------------------------------------------------ the app
resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: names.environment
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource environmentShare 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: containerEnv
  name: 'data'
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: dataShare.name
      accessMode: 'ReadWrite'
    }
  }
}

var appFqdn = '${names.app}.${containerEnv.properties.defaultDomain}'
var modelBaseUrl = 'https://${names.openAi}.openai.azure.com/openai/v1'
var vaultSecret = '${vault.properties.vaultUri}secrets'

// What the API and the worker both read. Model calls go through the gateway, whose
// data-class policy lets a cloud endpoint see synthetic projects only.
var sharedEnv = concat([
  { name: 'DATA_DIR', value: '/data' }
  { name: 'DATABASE_URL', secretRef: 'database-url' }
  { name: 'GITHUB_MODELS_BASE_URL', value: modelBaseUrl }
  { name: 'TEXT_MODEL', value: model.name }
  { name: 'VISION_MODEL', value: model.name }
  { name: 'TEXT_MODEL_FALLBACKS', value: '' }
  { name: 'VISION_MODEL_FALLBACKS', value: '' }
  { name: 'AZURE_OPENAI_API_KEY', secretRef: 'azure-openai-key' }
  { name: 'LLM_DAILY_BUDGET_USD', value: dailyBudgetUsd }
], empty(modelPricesJson) ? [] : [
  { name: 'MODEL_PRICES', value: modelPricesJson }
])
var dataMount = [
  { volumeName: 'data', mountPath: '/data' }
]

resource app 'Microsoft.App/containerApps@2024-03-01' = if (deployApp) {
  name: names.app
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      // No public ingress without sign-in: nginx adds the API key, so whoever reaches
      // the app has full access to it.
      ingress: {
        external: !empty(signInClientId)
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
        // Declared on every deploy: a deploy that left it out would remove the binding.
        customDomains: empty(customDomain) ? [] : [
          union({ name: customDomain, bindingType: empty(customDomainCertificateId) ? 'Disabled' : 'SniEnabled' },
                empty(customDomainCertificateId) ? {} : { certificateId: customDomainCertificateId })
        ]
      }
      registries: [
        {
          server: 'ghcr.io'
          username: ghcrUser
          passwordSecretRef: 'ghcr-token'
        }
      ]
      secrets: [
        { name: 'api-key', keyVaultUrl: '${vaultSecret}/api-key', identity: identity.id }
        { name: 'database-url', keyVaultUrl: '${vaultSecret}/database-url', identity: identity.id }
        { name: 'ghcr-token', keyVaultUrl: '${vaultSecret}/ghcr-token', identity: identity.id }
        { name: 'sign-in-secret', keyVaultUrl: '${vaultSecret}/sign-in-secret', identity: identity.id }
        { name: 'azure-openai-key', value: openAi.listKeys().key1 }
      ]
    }
    template: {
      // 2 vCPU and 4 GiB in all while awake; nothing while scaled to zero.
      containers: [
        {
          name: 'web'
          image: '${registry}/web:${imageTag}'
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            { name: 'BACKEND_URL', value: 'http://localhost:8000' }
            { name: 'API_KEY', secretRef: 'api-key' }
          ]
          probes: [
            { type: 'Readiness', httpGet: { path: '/', port: 8080 }, periodSeconds: 10 }
          ]
        }
        {
          name: 'api'
          image: '${registry}/backend:${imageTag}'
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: concat(sharedEnv, [
            { name: 'API_KEY', secretRef: 'api-key' }
            { name: 'INBOX_DIR', value: '/data/inbox' }
            { name: 'CORS_ORIGINS', value: 'https://${appFqdn}' }
            // Synthetic cases only, no uploads: real documents run on the client's machine.
            { name: 'HOSTED_DEMO', value: '1' }
            { name: 'SOURCE_URL', value: sourceUrl }
          ])
          volumeMounts: dataMount
          probes: [
            { type: 'Startup', httpGet: { path: '/health', port: 8000 }, periodSeconds: 3, failureThreshold: 40 }
            { type: 'Liveness', httpGet: { path: '/health', port: 8000 }, periodSeconds: 30 }
          ]
        }
        {
          name: 'worker'
          image: '${registry}/backend:${imageTag}'
          command: ['python', '-m', 'app.jobs.worker']
          args: ['--pipelines', pipelines]
          resources: { cpu: json('0.75'), memory: '1.5Gi' }
          env: sharedEnv
          volumeMounts: dataMount
        }
      ]
      // Wakes on the first request and sleeps when idle. A job the scale-down cuts off is
      // retried by the sweeper and resumes from its checkpoints. One replica: one writer
      // on the file share.
      scale: {
        minReplicas: 0
        maxReplicas: 1
        rules: [
          { name: 'http', http: { metadata: { concurrentRequests: '50' } } }
        ]
      }
      volumes: [
        // The image runs as uid 1000 (backend/Dockerfile): the share is mounted as that user.
        { name: 'data', storageType: 'AzureFile', storageName: environmentShare.name, mountOptions: 'uid=1000,gid=1000' }
      ]
    }
  }
}

// Entra ID sign-in in front of every path. Only the users assigned to the sign-in app
// registration get in (setup.sh turns on "assignment required").
resource signIn 'Microsoft.App/containerApps/authConfigs@2024-03-01' = if (deployApp && !empty(signInClientId)) {
  parent: app
  name: 'current'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
          clientId: signInClientId
          clientSecretSettingName: 'sign-in-secret'
        }
        validation: {
          allowedAudiences: [
            'api://${signInClientId}'
          ]
        }
      }
    }
  }
}

output environmentDomain string = containerEnv.properties.defaultDomain
output appUrl string = empty(customDomain) ? 'https://${appFqdn}' : 'https://${customDomain}'
output storageAccount string = storage.name
output postgresHost string = postgres.outputs.fqdn
output modelEndpoint string = modelBaseUrl
