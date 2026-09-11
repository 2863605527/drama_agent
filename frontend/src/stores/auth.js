import { defineStore } from 'pinia'
import { authApi } from '@/api/auth'
import { getToken, setAuth, clearAuth, getStoredUser } from '@/api/request'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getToken(),
    user: getStoredUser()
  }),
  getters: {
    isLogin: (s) => !!s.token,
    username: (s) => s.user?.username || ''
  },
  actions: {
    async login(username, password) {
      const data = await authApi.login(username, password)
      this.token = data.access_token
      this.user = { username: data.username }
      setAuth(this.token, this.user)
      return data
    },
    async register(username, password) {
      const data = await authApi.register(username, password)
      this.token = data.access_token
      this.user = { username: data.username }
      setAuth(this.token, this.user)
      return data
    },
    async fetchMe() {
      const me = await authApi.me()
      this.user = { id: me.id, username: me.username }
      setAuth(this.token, this.user)
      return me
    },
    logout() {
      this.token = ''
      this.user = null
      clearAuth()
    }
  }
})
