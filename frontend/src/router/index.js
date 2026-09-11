import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '@/api/request'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' }
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      { path: '', name: 'workspace', component: () => import('@/views/WorkspaceView.vue') }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 全局前置守卫：无 token 一律进登录页
router.beforeEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Drama-Agent` : 'Drama-Agent 短剧生成工作台'
  if (!to.meta.public && !getToken()) {
    return { name: 'login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : {} }
  }
  if (to.name === 'login' && getToken()) {
    return { name: 'workspace' }
  }
  return true
})

export default router
