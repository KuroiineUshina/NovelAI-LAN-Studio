package com.novelai.lanstudio;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class OfflineGalleryPageTest {
    @Test
    public void offlinePageIsReadOnlyAndContainsOnlyDownloadAction() {
        String html = OfflineGalleryPage.html();

        assertTrue(html.contains("임시 보관"));
        assertTrue(html.contains("즐겨찾기"));
        assertTrue(html.contains("읽기 전용"));
        assertTrue(html.contains("novelai-offline-download://image/"));
        assertTrue(html.contains("정보 보존</a>"));
        assertTrue(html.contains("정보 제거</a>"));
        assertTrue(html.contains("className='card-download'"));
        assertTrue(html.contains("downloadUrl(item.id,'remove')"));
        assertTrue(html.contains("downloadUrl(item.id,'preserve')"));
        assertTrue(html.contains("actions.append(exportLinks(item.id))"));
        assertFalse(html.contains("웹훅"));
        assertFalse(html.contains("영구 삭제"));
        assertFalse(html.contains("즐겨찾기 해제"));
        assertFalse(html.toLowerCase().contains("prompt"));
        assertFalse(html.toLowerCase().contains("seed"));
        assertFalse(html.toLowerCase().contains("settings"));
    }

    @Test
    public void offlineViewerSupportsZoomNavigationAndSwipeClose() {
        String html = OfflineGalleryPage.html();

        assertTrue(html.contains("pointerdown"));
        assertTrue(html.contains("pointermove"));
        assertTrue(html.contains("state.scale>1.01"));
        assertTrue(html.contains("dy>110"));
        assertTrue(html.contains("navigate(dx<0?1:-1)"));
        assertTrue(html.contains("축소해 화면맞춤으로 돌아가기"));
        assertTrue(html.contains("아래로 닫기"));
    }
}
