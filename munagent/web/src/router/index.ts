import { createRouter, createWebHistory } from "vue-router";
import LandingView from "../views/LandingView.vue";
import ScenariosView from "../views/ScenariosView.vue";
import SettingsView from "../views/SettingsView.vue";
import ScenarioView from "../views/ScenarioView.vue";
import DesignerView from "../views/DesignerView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "landing", component: LandingView },
    { path: "/scenarios", name: "scenarios", component: ScenariosView },
    { path: "/design/:id", name: "design", component: DesignerView },
    { path: "/settings", name: "settings", component: SettingsView },
    { path: "/scenarios/:id", name: "scenario", component: ScenarioView },
  ],
});

export default router;
