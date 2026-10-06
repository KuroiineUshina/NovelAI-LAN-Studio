package com.novelai.lanstudio;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;

public final class StandaloneImageStore {
    private final File temporaryDirectory;
    private final File favoriteDirectory;
    private final File thumbnailTemporaryDirectory;
    private final File thumbnailFavoriteDirectory;

    public StandaloneImageStore(Context context) {
        File root = new File(context.getFilesDir(), "standalone-images");
        temporaryDirectory = new File(root, "temporary");
        favoriteDirectory = new File(root, "favorites");
        thumbnailTemporaryDirectory = new File(root, "thumbnails/temporary");
        thumbnailFavoriteDirectory = new File(root, "thumbnails/favorites");
        ensureDirectories();
    }

    public SavedImage saveGenerated(byte[] data, String imageId) throws IOException {
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(data, 0, data.length, bounds);
        if (bounds.outWidth < 1 || bounds.outHeight < 1 || bounds.outWidth > 8192 || bounds.outHeight > 8192) {
            throw new IOException("정상적인 생성 이미지가 아닙니다.");
        }
        File image = new File(temporaryDirectory, imageId + ".png");
        File thumbnail = new File(thumbnailTemporaryDirectory, imageId + ".jpg");
        atomicWrite(image, data);
        try {
            createThumbnail(data, thumbnail, bounds.outWidth, bounds.outHeight);
        } catch (IOException | RuntimeException error) {
            image.delete();
            thumbnail.delete();
            throw error;
        }
        return new SavedImage(
            image.getAbsolutePath(), thumbnail.getAbsolutePath(),
            bounds.outWidth, bounds.outHeight, "image/png"
        );
    }

    public SavedPaths moveFavorite(StandaloneDatabase.StoredImage image, boolean favorite) throws IOException {
        File source = new File(image.filePath);
        File sourceThumbnail = new File(image.thumbnailPath);
        File destination = new File(favorite ? favoriteDirectory : temporaryDirectory, image.id + ".png");
        File destinationThumbnail = new File(
            favorite ? thumbnailFavoriteDirectory : thumbnailTemporaryDirectory,
            image.id + ".jpg"
        );
        ensureDirectories();
        boolean mainMoved = false;
        try {
            move(source, destination);
            mainMoved = true;
            move(sourceThumbnail, destinationThumbnail);
        } catch (IOException error) {
            if (mainMoved && destination.exists() && !source.exists()) {
                try { move(destination, source); } catch (IOException ignored) { }
            }
            throw error;
        }
        return new SavedPaths(destination.getAbsolutePath(), destinationThumbnail.getAbsolutePath());
    }

    public void delete(StandaloneDatabase.StoredImage image) {
        new File(image.filePath).delete();
        new File(image.thumbnailPath).delete();
    }

    private void ensureDirectories() {
        for (File directory : new File[]{temporaryDirectory, favoriteDirectory, thumbnailTemporaryDirectory, thumbnailFavoriteDirectory}) {
            if (directory.isDirectory() || directory.mkdirs() || directory.isDirectory()) continue;
            throw new IllegalStateException("모바일 이미지 저장 폴더를 만들지 못했습니다.");
        }
    }

    private static void atomicWrite(File destination, byte[] data) throws IOException {
        File temporary = new File(destination.getParentFile(), "." + destination.getName() + ".part");
        try (FileOutputStream stream = new FileOutputStream(temporary)) {
            stream.write(data);
            stream.flush();
            stream.getFD().sync();
        }
        move(temporary, destination);
    }

    private static void move(File source, File destination) throws IOException {
        try {
            Files.move(source.toPath(), destination.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } catch (AtomicMoveNotSupportedException error) {
            Files.move(source.toPath(), destination.toPath(), StandardCopyOption.REPLACE_EXISTING);
        }
    }

    private static void createThumbnail(byte[] data, File destination, int width, int height) throws IOException {
        BitmapFactory.Options options = new BitmapFactory.Options();
        int largest = Math.max(width, height);
        int sampleSize = 1;
        while (largest / sampleSize > 1280) sampleSize *= 2;
        options.inSampleSize = sampleSize;
        Bitmap decoded = BitmapFactory.decodeByteArray(data, 0, data.length, options);
        if (decoded == null) throw new IOException("썸네일을 만들지 못했습니다.");
        int targetWidth = decoded.getWidth();
        int targetHeight = decoded.getHeight();
        double ratio = Math.min(1.0, 640.0 / Math.max(targetWidth, targetHeight));
        Bitmap scaled = Bitmap.createScaledBitmap(
            decoded,
            Math.max(1, (int) Math.round(targetWidth * ratio)),
            Math.max(1, (int) Math.round(targetHeight * ratio)),
            true
        );
        Bitmap flattened = Bitmap.createBitmap(scaled.getWidth(), scaled.getHeight(), Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(flattened);
        canvas.drawColor(0xff000000);
        canvas.drawBitmap(scaled, 0f, 0f, null);
        File temporary = new File(destination.getParentFile(), "." + destination.getName() + ".part");
        try (FileOutputStream stream = new FileOutputStream(temporary)) {
            if (!flattened.compress(Bitmap.CompressFormat.JPEG, 84, stream)) {
                throw new IOException("썸네일을 압축하지 못했습니다.");
            }
            stream.flush();
            stream.getFD().sync();
        } finally {
            if (scaled != decoded) scaled.recycle();
            decoded.recycle();
            flattened.recycle();
        }
        move(temporary, destination);
    }

    public static final class SavedImage {
        public final String filePath;
        public final String thumbnailPath;
        public final int width;
        public final int height;
        public final String mimeType;

        SavedImage(String filePath, String thumbnailPath, int width, int height, String mimeType) {
            this.filePath = filePath;
            this.thumbnailPath = thumbnailPath;
            this.width = width;
            this.height = height;
            this.mimeType = mimeType;
        }
    }

    public static final class SavedPaths {
        public final String filePath;
        public final String thumbnailPath;

        SavedPaths(String filePath, String thumbnailPath) {
            this.filePath = filePath;
            this.thumbnailPath = thumbnailPath;
        }
    }
}
