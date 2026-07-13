<script setup lang="ts">
import { computed } from "vue";
import { renderMarkdown } from "../../utils/renderMarkdown";

const props = defineProps<{ source: string }>();

const html = computed(() => renderMarkdown(props.source));
</script>

<template>
  <div class="md-body" v-html="html" />
</template>

<style scoped>
.md-body {
  font-size: 0.9rem;
  line-height: 1.55;
  word-break: break-word;
}
.md-body :deep(p) {
  margin: 0 0 0.65em;
}
.md-body :deep(p:last-child) {
  margin-bottom: 0;
}
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) {
  margin: 0.85em 0 0.4em;
  line-height: 1.3;
  font-weight: 600;
}
.md-body :deep(h1) {
  font-size: 1.15rem;
}
.md-body :deep(h2) {
  font-size: 1.05rem;
}
.md-body :deep(h3) {
  font-size: 0.98rem;
}
.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 0.35em 0 0.65em;
  padding-left: 1.35em;
}
.md-body :deep(li) {
  margin: 0.2em 0;
}
.md-body :deep(blockquote) {
  margin: 0.5em 0;
  padding: 0.35em 0.75em;
  border-left: 3px solid var(--border);
  color: var(--text-muted);
}
.md-body :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.85em;
  background: var(--chip-bg);
  padding: 0.1em 0.35em;
  border-radius: 4px;
}
.md-body :deep(pre) {
  margin: 0.5em 0;
  padding: 0.65em 0.75em;
  border-radius: 8px;
  background: #1e1e1e;
  color: #e8e8e8;
  overflow-x: auto;
  font-size: 0.82rem;
  line-height: 1.45;
}
.md-body :deep(pre code) {
  background: none;
  padding: 0;
  color: inherit;
}
.md-body :deep(a) {
  color: var(--accent);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.md-body :deep(hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: 0.75em 0;
}
.md-body :deep(table) {
  border-collapse: collapse;
  font-size: 0.85em;
  margin: 0.5em 0;
}
.md-body :deep(th),
.md-body :deep(td) {
  border: 1px solid var(--border);
  padding: 0.35em 0.55em;
}
</style>
