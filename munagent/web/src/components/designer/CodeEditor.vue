<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { yaml } from "@codemirror/lang-yaml";
import { markdown } from "@codemirror/lang-markdown";
import { basicSetup } from "codemirror";

const props = defineProps<{
  modelValue: string;
  path: string;
}>();

const emit = defineEmits<{ "update:modelValue": [string] }>();

const host = ref<HTMLElement | null>(null);
let view: EditorView | null = null;
let syncing = false;

function languageFor(path: string) {
  if (path.endsWith(".yaml") || path.endsWith(".yml")) return yaml();
  if (path.endsWith(".md") || path.endsWith(".markdown")) return markdown();
  return [];
}

const lightTheme = EditorView.theme(
  {
    "&": {
      height: "100%",
      backgroundColor: "var(--bg)",
      color: "var(--text)",
    },
    ".cm-content": {
      caretColor: "var(--accent)",
      padding: "12px 0",
    },
    ".cm-cursor, .cm-dropCursor": {
      borderLeftColor: "var(--accent)",
    },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
      backgroundColor: "#dbeafe !important",
    },
    ".cm-gutters": {
      backgroundColor: "var(--panel-bg)",
      color: "var(--text-muted)",
      border: "none",
    },
    ".cm-activeLineGutter": {
      backgroundColor: "var(--hover)",
    },
    ".cm-activeLine": {
      backgroundColor: "var(--hover)",
    },
    ".cm-scroller": {
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, monospace',
      fontSize: "13px",
      lineHeight: "1.55",
    },
  },
  { dark: false }
);

function createState(doc: string) {
  return EditorState.create({
    doc,
    extensions: [
      basicSetup,
      history(),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      languageFor(props.path),
      lightTheme,
      EditorView.lineWrapping,
      EditorView.updateListener.of((update) => {
        if (update.docChanged && !syncing) {
          emit("update:modelValue", update.state.doc.toString());
        }
      }),
    ],
  });
}

function mountView(doc: string) {
  if (!host.value) return;
  view?.destroy();
  view = new EditorView({
    state: createState(doc),
    parent: host.value,
  });
}

function replaceDoc(next: string) {
  if (!view || view.state.doc.toString() === next) return;
  syncing = true;
  view.dispatch({
    changes: { from: 0, to: view.state.doc.length, insert: next },
  });
  syncing = false;
}

onMounted(() => mountView(props.modelValue));

watch(
  () => props.modelValue,
  (v) => replaceDoc(v)
);

watch(
  () => props.path,
  () => mountView(props.modelValue)
);

onBeforeUnmount(() => {
  view?.destroy();
  view = null;
});
</script>

<template>
  <div ref="host" class="cm-host" />
</template>

<style scoped>
.cm-host {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.cm-host :deep(.cm-editor) {
  height: 100%;
}
</style>
