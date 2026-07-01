<script setup lang="ts">
import {
	BILLBILL,
	DISCORD,
	GITHUB_LINK,
	QQ_GROUP,
	TWITTER,
	XHS,
} from "@/utils/const";
import NavUser from "./NavUser.vue";
import { listTasks, type TaskInfo } from "@/apis/commonApi";
import { ref, onMounted } from "vue";
import { useRouter } from "vue-router";

import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarGroup,
	SidebarGroupContent,
	SidebarGroupLabel,
	SidebarHeader,
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
	type SidebarProps,
	SidebarRail,
} from "@/components/ui/sidebar";

// ---- Props ----

const props = defineProps<SidebarProps>();
const router = useRouter();

// ---- Reactive State ----

const historyTasks = ref<TaskInfo[]>([]);
const historyLoading = ref(false);
const historyError = ref(false);

/** 导航菜单数据 */
const data = ref({
	navMain: [
		{
			title: "开始",
			url: "#",
			items: [
				{
					title: "开始新任务",
					url: "#",
					isActive: false,
				},
			],
		},
		{
			title: "历史任务",
			url: "#",
			items: [] as { title: string; url: string; isActive: boolean; taskId: string }[],
		},
	],
});

/** 加载历史任务 */
const loadHistory = async () => {
	historyLoading.value = true;
	historyError.value = false;
	try {
		const response = await listTasks();
		const tasks = response.data || [];
		historyTasks.value = tasks;
		data.value.navMain[1].items = tasks.map((t) => ({
			title: t.title.substring(0, 40) + (t.title.length > 40 ? "..." : ""),
			url: "#",
			isActive: false,
			taskId: t.task_id,
		}));
	} catch (e) {
		console.error("加载历史任务失败:", e);
		historyError.value = true;
		historyTasks.value = [];
		data.value.navMain[1].items = [];
	} finally {
		historyLoading.value = false;
	}
};

/** 点击历史任务 */
const clickHistoryItem = (taskId: string) => {
	router.push(`/task/${taskId}`);
};

/** 点击新任务 */
const clickNewTask = () => {
	router.push("/");
};

onMounted(() => {
	loadHistory();
});

const socialMedia = [
	{
		name: "QQ",
		url: QQ_GROUP,
		icon: "/qq.svg",
	},
	{
		name: "Twitter",
		url: TWITTER,
		icon: "/twitter.svg",
	},
	{
		name: "GitHub",
		url: GITHUB_LINK,
		icon: "/github.svg",
	},
	{
		name: "哔哩哔哩",
		url: BILLBILL,
		icon: "/bilibili.svg",
	},
	{
		name: "小红书",
		url: XHS,
		icon: "/xiaohongshu.svg",
	},
	{
		name: "Discord",
		url: DISCORD,
		icon: "/discord.svg",
	},
];
</script>

<template>
  <Sidebar v-bind="props">
    <SidebarHeader>
      <!-- 图标 -->
      <div class="flex items-center gap-2 h-15">
        <router-link to="/" class="flex items-center gap-2">
          <img src="@/assets/icon.png" alt="logo" class="w-10 h-10">
          <div class="text-lg font-bold">MathModelAgent</div>
        </router-link>
      </div>
    </SidebarHeader>
    <SidebarContent>
      <SidebarGroup v-for="item in data.navMain" :key="item.title">
        <SidebarGroupLabel>{{ item.title }}</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            <template v-if="item.title === '历史任务'">
              <div v-if="historyLoading" class="px-2 py-1.5 text-xs text-muted-foreground">
                加载中...
              </div>
              <div v-else-if="historyError" class="px-2 py-1.5 text-xs text-destructive">
                历史任务加载失败，<a href="#" class="underline" @click.prevent="loadHistory">重试</a>
              </div>
              <div v-else-if="item.items.length === 0" class="px-2 py-1.5 text-xs text-muted-foreground">
                暂无历史任务
              </div>
            </template>
            <SidebarMenuItem v-for="(childItem, index) in item.items" :key="childItem.title + index">
              <SidebarMenuButton as-child :is-active="childItem.isActive">
                <a v-if="item.title === '开始'" href="#" @click.prevent="clickNewTask">{{ childItem.title }}</a>
                <a v-else href="#" @click.prevent="clickHistoryItem((childItem as any).taskId)" :title="(childItem as any).taskId">{{ childItem.title }}</a>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>
    <SidebarRail />
    <SidebarFooter>
      <NavUser />
    </SidebarFooter>
    <SidebarFooter>
      <!-- 展示图标社交媒体  -->
      <div class="flex items-center gap-4 justify-centermb-4 border-t  border-light-purple pt-3">
        <a v-for="item in socialMedia" :href="item.url" target="_blank">
          <img :src="item.icon" :alt="item.name" width="24" height="24" class="icon">
        </a>
      </div>
    </SidebarFooter>
  </Sidebar>
</template>