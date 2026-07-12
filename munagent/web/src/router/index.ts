import { createRouter, createWebHistory } from "vue-router";
import HomeView from "../views/HomeView.vue";
import SettingsView from "../views/SettingsView.vue";
import ScenarioView from "../views/ScenarioView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "home", component: HomeView },
    { path: "/settings", name: "settings", component: SettingsView },
    { path: "/scenarios/:id", name: "scenario", component: ScenarioView },
  ],
});

export default router;
