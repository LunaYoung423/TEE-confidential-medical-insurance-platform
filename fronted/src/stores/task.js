import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useTaskStore = defineStore('task', () => {
  const tasks = ref([])
  const operationLogs = ref([])

  function addLog(log) {
    operationLogs.value.unshift({
      time: log.time || new Date().toLocaleString(),
      type: log.type,
      user: log.user || 'admin',
      taskId: log.taskId,
      containerId: log.containerId,
      detail: log.detail,
      status: log.status
    })
  }

  return { tasks, operationLogs, addLog }
})