import { defineStore } from 'pinia'

let seq = 0

export const useToastStore = defineStore('toast', {
  state: () => ({ list: [] }),
  actions: {
    push(msg, type = 'ok', timeout = 2600) {
      const id = ++seq
      this.list.push({ id, msg, type })
      setTimeout(() => this.dismiss(id), timeout)
    },
    ok(msg) { this.push(msg, 'ok') },
    err(msg) { this.push(msg, 'err', 4000) },
    dismiss(id) { this.list = this.list.filter(t => t.id !== id) }
  }
})
