package com.novelai.lanstudio;

import static org.junit.Assert.*;
import org.junit.Test;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

public class ExportPixelsTest {
    @Test public void ordinaryTransparencyAndColorsAreUntouched() {
        int[] pixels = {0x00010203,0x01040506,0x7f123456,0x80123456,0xfe654321,0xff654321};
        int[] before = pixels.clone();
        ExportPixels.scrub(pixels,3,2);
        assertArrayEquals(before,pixels);
    }

    @Test public void allRecognizedPayloadsAreErased() {
        for (String magic : new String[]{"stealth_pngcomp","stealth_pnginfo","stealth_rgbcomp","stealth_rgbinfo"}) {
            boolean alpha = magic.contains("png");
            int[] pixels = new int[32*64];
            Arrays.fill(pixels,0xff6597c9);
            byte[] payload = (magic + "private payload including prompt").getBytes(StandardCharsets.US_ASCII);
            int[] shifts = alpha ? new int[]{24} : new int[]{16,8,0};
            int bit=0;
            for (int x=0;x<32;x++) for(int y=0;y<64;y++) for(int shift:shifts) {
                if(bit<payload.length*8) {
                    int value=(payload[bit/8] >>> (7-bit%8))&1;
                    pixels[y*32+x]=(pixels[y*32+x]&~(1<<shift))|(value<<shift);
                    bit++;
                }
            }
            assertEquals(magic,ExportPixels.header(pixels,32,64,alpha));
            ExportPixels.scrub(pixels,32,64);
            assertNotEquals(magic,ExportPixels.header(pixels,32,64,alpha));
            for(int pixel:pixels) {
                if(alpha) assertEquals(0xff6597c9,pixel);
                else assertEquals(0,pixel&0x00010101);
            }
        }
    }

    @Test public void allExifOrientationsKeepVisualLayout() {
        int[] input={1,2,3,4,5,6};
        int[][] expected={input,{3,2,1,6,5,4},{6,5,4,3,2,1},{4,5,6,1,2,3},{1,4,2,5,3,6},{4,1,5,2,6,3},{6,3,5,2,4,1},{3,6,2,5,1,4}};
        for(int orientation=1;orientation<=8;orientation++) assertArrayEquals(expected[orientation-1],ExportPixels.orient(input,3,2,orientation));
        assertArrayEquals(new int[]{1,2,3,4,5,6},input);
    }
}
