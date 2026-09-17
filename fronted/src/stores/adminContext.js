import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  getAdminAlerts,
  getClusterStatus,
  getEpcUsage,
  getAudit
} from '../api'

export const useAdminContextStore = defineStore('adminContext', () => {
  const loading = ref(false)
  const clusterStatus = ref(null)
  const epcUsage = ref(null)
  const recentAudit = ref([])
  const alerts = ref([])
  const refreshKey = ref(0)

  const unhandledAlertsCount = computed(() => alerts.value.filter(a => !a.read).length)

  async function bootstrap() {
    loading.value = true
    try {
      const [s, u, audit, a] = await Promise.all([
        getClusterStatus(),
        getEpcUsage(),
        getAudit({ limit: 5 }),
        getAdminAlerts()
      ])
      clusterStatus.value = s
      epcUsage.value = u
      recentAudit.value = audit.items || []
      alerts.value = a
    } finally {
      loading.value = false
    }
  }

  function markAllAlertsRead() {
    alerts.value = alerts.value.map(a => ({ ...a, read: true }))
  }

  function bumpRefresh() {
    refreshKey.value += 1
  }

  return {
    loading,
    clusterStatus,
    epcUsage,
    recentAudit,
    alerts,
    unhandledAlertsCount,
    refreshKey,
    bootstrap,
    markAllAlertsRead,
    bumpRefresh
  }
})

