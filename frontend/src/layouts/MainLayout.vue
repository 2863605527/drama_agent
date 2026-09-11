<template>
  <div class="layout">
    <AppSidebar @new-task="taskStore.newBlank()" @select="(id) => taskStore.selectFromSidebar(id)" />
    <main class="main-area">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import AppSidebar from '@/components/AppSidebar.vue'
import { useTaskStore } from '@/stores/task'
const taskStore = useTaskStore()
</script>

<style scoped>
.layout { display: flex; height: 100vh; overflow: hidden; }
.main-area { flex: 1; height: 100vh; overflow: hidden; display: flex; flex-direction: column; background: var(--bg-app); }
</style>
