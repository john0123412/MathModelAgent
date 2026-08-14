import type { Ref, WatchSource } from "vue";
import { nextTick, onMounted, ref, watch } from "vue";

const STICKY_THRESHOLD = 40;

/**
 * Keep a live message/list panel pinned to its newest item until the user
 * scrolls up. Once the user returns near the bottom, automatic scrolling is
 * enabled again.
 */
export function useStickyScroll(
	scrollRef: Ref<HTMLElement | null>,
	source: WatchSource,
) {
	const isPinnedToBottom = ref(true);

	function scrollToBottom() {
		const element = scrollRef.value;
		if (element) element.scrollTop = element.scrollHeight;
	}

	function onScroll() {
		const element = scrollRef.value;
		if (!element) return;
		isPinnedToBottom.value =
			element.scrollHeight - element.scrollTop - element.clientHeight <=
			STICKY_THRESHOLD;
	}

	watch(
		source,
		() => {
			if (isPinnedToBottom.value) nextTick(scrollToBottom);
		},
		{ deep: true },
	);

	onMounted(() => nextTick(scrollToBottom));

	return { onScroll };
}
