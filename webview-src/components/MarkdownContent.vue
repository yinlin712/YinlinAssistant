<script setup lang="ts">
import { computed } from "vue";
import createDOMPurify from "dompurify";
import MarkdownIt from "markdown-it";
import markdownItTaskLists from "markdown-it-task-lists";

const props = defineProps<{
  content: string;
}>();

const renderedHtml = computed(() => {
  try {
    const html = getMarkdownRenderer().render(props.content ?? "");
    return getHtmlSanitizer().sanitize(html, {
      USE_PROFILES: { html: true },
    });
  } catch (error) {
    return `<pre>${escapeHtml(String(props.content ?? ""))}</pre>`;
  }
});

/**
 * 创建供 Webview 复用的 Markdown 渲染器。
 */
function createMarkdownRenderer() {
  const renderer = new MarkdownIt({
    html: false,
    linkify: true,
    breaks: false,
  }) as any;

  renderer.use(markdownItTaskLists, { enabled: true });

  const defaultLinkRender = renderer.renderer.rules.link_open
    ?? ((tokens: any, index: number, options: any, _env: any, self: any) => self.renderToken(tokens, index, options));

  renderer.renderer.rules.link_open = (
    tokens: any,
    index: number,
    options: any,
    env: any,
    self: any,
  ) => {
    tokens[index].attrSet("target", "_blank");
    tokens[index].attrSet("rel", "noopener noreferrer");
    return defaultLinkRender(tokens, index, options, env, self);
  };

  return renderer;
}

/**
 * 创建可在 Webview 中稳定工作的 HTML 清洗器。
 */
function createHtmlSanitizer() {
  const maybeFactory = createDOMPurify as unknown as {
    (window: Window): { sanitize(input: string, options?: Record<string, unknown>): string };
    sanitize?: (input: string, options?: Record<string, unknown>) => string;
  };

  if (typeof maybeFactory.sanitize === "function") {
    return {
      sanitize: maybeFactory.sanitize.bind(maybeFactory),
    };
  }

  return maybeFactory(window);
}

let cachedMarkdownRenderer: ReturnType<typeof createMarkdownRenderer> | null = null;
let cachedHtmlSanitizer: ReturnType<typeof createHtmlSanitizer> | null = null;

/**
 * 惰性获取 Markdown 渲染器，避免模块初始化阶段出错。
 */
function getMarkdownRenderer() {
  if (!cachedMarkdownRenderer) {
    cachedMarkdownRenderer = createMarkdownRenderer();
  }

  return cachedMarkdownRenderer;
}

/**
 * 惰性获取 HTML 清洗器，避免模块初始化阶段出错。
 */
function getHtmlSanitizer() {
  if (!cachedHtmlSanitizer) {
    cachedHtmlSanitizer = createHtmlSanitizer();
  }

  return cachedHtmlSanitizer;
}

/**
 * 在 Markdown 渲染失败时退化为纯文本，避免整块 Webview 直接空白。
 */
function escapeHtml(source: string): string {
  return source
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
</script>

<template>
  <div class="markdown-body" v-html="renderedHtml" />
</template>
