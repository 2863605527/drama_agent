<template>
  <div class="login-page">
    <div class="login-bg">
      <span class="orb orb1"></span>
      <span class="orb orb2"></span>
      <span class="orb orb3"></span>
    </div>

    <div class="login-card fade-up">
      <div class="brand">
        <div class="logo">🎬</div>
        <div>
          <h1>Drama-Agent</h1>
          <p>AI 短剧智能生成工作台</p>
        </div>
      </div>

      <div class="tabs">
        <button :class="{ active: mode === 'login' }" @click="mode = 'login'">
          登录
        </button>
        <button
          :class="{ active: mode === 'register' }"
          @click="mode = 'register'"
        >
          注册
        </button>
      </div>

      <form @submit.prevent="submit">
        <label class="field">
          <span>用户名</span>
          <input
            class="input"
            :class="{ invalid: mode === 'register' && nameErr }"
            v-model.trim="username"
            :placeholder="
              mode === 'register'
                ? '字母开头，3~20位，仅字母/数字/下划线'
                : '请输入用户名'
            "
            autocomplete="username"
          />
          <small v-if="mode === 'register' && nameErr" class="err">{{
            nameErr
          }}</small>
        </label>
        <label class="field">
          <span>密码</span>
          <input
            class="input"
            :class="{ invalid: mode === 'register' && pwdErr }"
            type="password"
            v-model="password"
            :placeholder="
              mode === 'register'
                ? '6~20位，仅字母/数字，不可含中文或特殊字符'
                : '请输入密码'
            "
            autocomplete="current-password"
          />
          <small v-if="mode === 'register' && pwdErr" class="err">{{
            pwdErr
          }}</small>
        </label>

        <button
          class="btn btn-primary submit"
          :disabled="
            loading || (mode === 'register' && (!!nameErr || !!pwdErr))
          "
        >
          <span v-if="loading" class="spin">◌</span>
          {{ mode === "login" ? "登 录" : "注册并登录" }}
        </button>
      </form>

      <p class="tip">
        登录后可在左下角「个人信息」中配置模型通道（CV / ARK / HTTP）与 Key
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from "vue";
import { useRouter, useRoute } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toast";
import { extractError } from "@/api/request";

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();
const toast = useToastStore();

const mode = ref("login");
const username = ref("");
const password = ref("");
const loading = ref(false);

// 与后端 auth/validators.py 保持一致的注册白名单
const USERNAME_RE = /^[A-Za-z][A-Za-z0-9_]{2,19}$/;
const PASSWORD_RE = /^[A-Za-z0-9]{6,20}$/;
const nameErr = computed(() => {
  if (mode.value !== "register" || !username.value) return "";
  return USERNAME_RE.test(username.value)
    ? ""
    : "账号需字母开头、3~20位，仅含字母/数字/下划线，不能有中文或特殊字符";
});
const pwdErr = computed(() => {
  if (mode.value !== "register" || !password.value) return "";
  return PASSWORD_RE.test(password.value)
    ? ""
    : "密码需6~20位，仅含英文字母和数字，不能有中文、空格或特殊字符";
});

async function submit() {
  if (!username.value || !password.value) {
    toast.err("请输入用户名和密码");
    return;
  }
  if (mode.value === "register") {
    if (nameErr.value) {
      toast.err(nameErr.value);
      return;
    }
    if (pwdErr.value) {
      toast.err(pwdErr.value);
      return;
    }
  }
  loading.value = true;
  try {
    if (mode.value === "login") {
      await auth.login(username.value, password.value);
      toast.ok("登录成功");
    } else {
      await auth.register(username.value, password.value);
      toast.ok("注册成功，已自动登录");
    }
    router.replace(route.query.redirect || { name: "workspace" });
  } catch (e) {
    toast.err(extractError(e));
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  height: 100vh;
  overflow: hidden;
  display: grid;
  place-items: center;
  background: radial-gradient(circle at 30% 20%, #1a1d2b 0%, #0e1016 70%);
}
.login-bg .orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.35;
  animation: orb-drift 16s ease-in-out infinite alternate;
}
@keyframes orb-drift {
  from { transform: translate(0, 0) scale(1); }
  to { transform: translate(30px, 24px) scale(1.08); }
}
.orb1 {
  width: 420px;
  height: 420px;
  background: #6366f1;
  top: -120px;
  left: -80px;
}
.orb2 {
  width: 360px;
  height: 360px;
  background: #8b5cf6;
  bottom: -120px;
  right: -60px;
  animation-delay: -6s;
}
.orb3 {
  width: 260px;
  height: 260px;
  background: #0ea5e9;
  top: 50%;
  left: 60%;
  opacity: 0.18;
  animation-delay: -3s;
}

.login-card {
  position: absolute;
  height: max-content;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  margin: auto;
  z-index: 2;
  width: 400px;
  max-width: 92vw;
  background: rgba(26, 30, 41, 0.82);
  backdrop-filter: blur(18px);
  border: 1px solid rgba(139,146,180,.22);
  border-radius: 18px;
  padding: 34px 32px;
  box-shadow: var(--shadow-lg), inset 0 1px 0 rgba(255,255,255,.06);
}
.brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 24px;
}
.logo {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  font-size: 28px;
  background: var(--gradient);
  box-shadow: 0 8px 20px rgba(99,102,241,.42), inset 0 1px 0 rgba(255,255,255,.22);
}
.brand h1 {
  font-size: 21px;
  letter-spacing: 0.5px;
}
.brand p {
  font-size: 12.5px;
  color: var(--text-3);
  margin-top: 2px;
}

.tabs {
  display: flex;
  gap: 6px;
  background: var(--bg-app);
  border-radius: 10px;
  padding: 4px;
  margin-bottom: 22px;
}
.tabs button {
  flex: 1;
  padding: 8px 0;
  border: none;
  background: transparent;
  color: var(--text-3);
  border-radius: 7px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.18s;
  font-family: inherit;
}
.tabs button.active {
  background: var(--gradient);
  color: #fff;
  font-weight: 600;
  box-shadow: 0 3px 10px rgba(99,102,241,.35);
}

.field {
  display: block;
  margin-bottom: 16px;
}
.field span {
  display: block;
  font-size: 12.5px;
  color: var(--text-2);
  margin-bottom: 6px;
}
.input.invalid {
  border-color: #ef4444;
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.15);
}
.field .err {
  display: block;
  margin-top: 5px;
  font-size: 11.5px;
  color: #f87171;
  line-height: 1.5;
}
.submit {
  width: 100%;
  padding: 11px;
  font-size: 15px;
  margin-top: 4px;
}
.tip {
  margin-top: 18px;
  font-size: 12px;
  color: var(--text-3);
  text-align: center;
  line-height: 1.6;
}
</style>
