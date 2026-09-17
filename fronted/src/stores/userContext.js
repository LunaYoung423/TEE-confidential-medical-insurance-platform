import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { getUserAccounts, getNotifications } from '../api'

export const useUserContextStore = defineStore('userContext', () => {
  const loading = ref(false)
  const accounts = ref([])
  const currentAccountId = ref('')
  const notifications = ref([])

  const currentAccount = computed(() => accounts.value.find(a => a.id === currentAccountId.value) || null)
  const unreadNotificationCount = computed(() => notifications.value.filter(n => !n.read).length)

  async function bootstrap() {
    loading.value = true
    try {
      accounts.value = await getUserAccounts()
      if (!currentAccountId.value && accounts.value.length) {
        currentAccountId.value = accounts.value[0].id
      }
      notifications.value = await getNotifications()
    } finally {
      loading.value = false
    }
  }

  function setAccount(id) {
    currentAccountId.value = id
  }

  function markAllNotificationsRead() {
    notifications.value = notifications.value.map(n => ({ ...n, read: true }))
  }

  return {
    loading,
    accounts,
    currentAccountId,
    currentAccount,
    notifications,
    unreadNotificationCount,
    bootstrap,
    setAccount,
    markAllNotificationsRead
  }
})

