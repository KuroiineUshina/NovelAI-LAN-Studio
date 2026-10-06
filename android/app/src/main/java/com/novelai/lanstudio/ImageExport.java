package com.novelai.lanstudio;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import androidx.exifinterface.media.ExifInterface;
import java.io.File;
import java.io.IOException;
import java.io.OutputStream;

final class ImageExport {
    private ImageExport() {}

    static void writeWithoutMetadata(File source, OutputStream output) throws IOException {
        Bitmap decoded = null;
        Bitmap clean = null;
        try {
            BitmapFactory.Options options = new BitmapFactory.Options();
            options.inJustDecodeBounds = true;
            BitmapFactory.decodeFile(source.getAbsolutePath(), options);
            long pixelsCount = (long) options.outWidth * options.outHeight;
            if (options.outWidth <= 0 || options.outHeight <= 0
                || options.outWidth > 8192 || options.outHeight > 8192
                || pixelsCount * 16L > Runtime.getRuntime().maxMemory() / 2L) {
                throw new IOException("Image is invalid or too large for safe metadata removal");
            }
            options.inJustDecodeBounds = false;
            options.inPreferredConfig = Bitmap.Config.ARGB_8888;
            options.inPremultiplied = false;
            decoded = BitmapFactory.decodeFile(source.getAbsolutePath(), options);
            if (decoded == null) throw new IOException("Image decoding failed");
            int width = decoded.getWidth(), height = decoded.getHeight();
            int[] pixels = new int[width * height];
            decoded.getPixels(pixels, 0, width, 0, 0, width, height);
            decoded.recycle();
            decoded = null;
            ExportPixels.scrub(pixels, width, height);
            int orientation = 1;
            try {
                orientation = new ExifInterface(source.getAbsolutePath())
                    .getAttributeInt(ExifInterface.TAG_ORIENTATION, 1);
            } catch (IOException ignored) {
                // Some supported bitmap formats have no EXIF container.
            }
            pixels = ExportPixels.orient(pixels, width, height, orientation);
            if (orientation >= 5 && orientation <= 8) {
                int swap = width; width = height; height = swap;
            }
            clean = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
            clean.setPremultiplied(false);
            clean.setPixels(pixels, 0, width, 0, 0, width, height);
            if (!clean.compress(Bitmap.CompressFormat.PNG, 100, output)) {
                throw new IOException("PNG export failed");
            }
            output.flush();
        } catch (OutOfMemoryError error) {
            throw new IOException("Not enough memory for metadata removal", error);
        } finally {
            if (decoded != null) decoded.recycle();
            if (clean != null) clean.recycle();
        }
    }
}
