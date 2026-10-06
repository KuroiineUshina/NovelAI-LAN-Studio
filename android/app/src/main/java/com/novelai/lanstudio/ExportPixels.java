package com.novelai.lanstudio;

/** Pixel-only helpers, independent of Android so privacy behavior is unit-testable. */
final class ExportPixels {
    private ExportPixels() {}

    static String header(int[] pixels, int width, int height, boolean alpha) {
        StringBuilder result = new StringBuilder();
        int value = 0, bits = 0;
        int[] shifts = alpha ? new int[]{24} : new int[]{16, 8, 0};
        for (int x = 0; x < width; x++) {
            for (int y = 0; y < height; y++) {
                for (int shift : shifts) {
                    value = (value << 1) | ((pixels[y * width + x] >>> shift) & 1);
                    if (++bits == 8) {
                        result.append((char) value);
                        bits = value = 0;
                        if (result.length() == 15) return result.toString();
                    }
                }
            }
        }
        return result.toString();
    }

    static void scrub(int[] pixels, int width, int height) {
        String alphaHeader = header(pixels, width, height, true);
        String rgbHeader = header(pixels, width, height, false);
        boolean alpha = alphaHeader.equals("stealth_pngcomp") || alphaHeader.equals("stealth_pnginfo");
        boolean rgb = rgbHeader.equals("stealth_rgbcomp") || rgbHeader.equals("stealth_rgbinfo");
        if (!alpha && !rgb) return;
        for (int i = 0; i < pixels.length; i++) {
            int pixel = pixels[i];
            if (rgb) pixel &= 0xfffefefe;
            if (alpha) {
                int a = pixel >>> 24;
                a = a >= 254 ? 255 : a & 254;
                pixel = (pixel & 0x00ffffff) | (a << 24);
            }
            pixels[i] = pixel;
        }
    }

    static int[] orient(int[] input, int width, int height, int orientation) {
        if (orientation < 2 || orientation > 8) return input;
        int outWidth = orientation >= 5 ? height : width;
        int[] output = new int[input.length];
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                int dx = x, dy = y;
                switch (orientation) {
                    case 2: dx = width - 1 - x; break;
                    case 3: dx = width - 1 - x; dy = height - 1 - y; break;
                    case 4: dy = height - 1 - y; break;
                    case 5: dx = y; dy = x; break;
                    case 6: dx = height - 1 - y; dy = x; break;
                    case 7: dx = height - 1 - y; dy = width - 1 - x; break;
                    case 8: dx = y; dy = width - 1 - x; break;
                    default: break;
                }
                output[dy * outWidth + dx] = input[y * width + x];
            }
        }
        return output;
    }
}
