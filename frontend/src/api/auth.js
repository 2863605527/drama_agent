import request from './request'

export const authApi = {
  login: (username, password) => request.post('/api/auth/login', { username, password }),
  register: (username, password) => request.post('/api/auth/register', { username, password }),
  me: () => request.get('/api/auth/me')
}
