// The demo's Postgres: Flexible Server, Burstable B1ms. The Azure free account covers
// 750 hours of B1ms and 32 GB a month for 12 months, which is this server run all month.
// The job queue uses LISTEN/NOTIFY, which Flexible Server supports.

param location string
param serverName string
param adminLogin string
@secure()
param adminPassword string
param databaseName string = 'tender'

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: serverName
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: adminLogin
    administratorLoginPassword: adminPassword
    storage: {
      storageSizeGB: 32
      autoGrow: 'Disabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: server
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// Public endpoint, TLS required (the server default), reachable from Azure services only.
// The 0.0.0.0 rule is Azure's switch for "Azure services"; no client IP is allowed. A
// private network would need a VNet-integrated Container Apps environment, which costs more.
resource azureServices 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: server
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

output fqdn string = server.properties.fullyQualifiedDomainName
