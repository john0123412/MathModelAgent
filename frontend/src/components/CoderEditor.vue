<script setup lang="ts">
import { ref } from 'vue'
import { SidebarProvider, Sidebar } from '@/components/ui/sidebar'
import { ScrollArea } from '@/components/ui/scroll-area'
import Files from '@/components/Files.vue'
import NotebookArea from '@/components/NotebookArea.vue'
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from '@/components/ui/resizable'

</script>
<template>
  <ResizablePanelGroup direction="horizontal" class="h-full w-full">
    <ResizablePanel :default-size="25" :min-size="15" class="h-full">
      <SidebarProvider>
        <Sidebar collapsible="none" class="h-full w-full overflow-hidden">
          <Files />
        </Sidebar>
      </SidebarProvider>
    </ResizablePanel>

    <ResizableHandle with-handle />
    <ResizablePanel :default-size="75" :min-size="30" class="h-full">
      <NotebookArea class="h-full min-w-0 pb-4" />
    </ResizablePanel>
  </ResizablePanelGroup>

</template>

<style scoped>
::-webkit-scrollbar {
  display: none;
  /* 或者 width: 0; height: 0; */
}
</style>
