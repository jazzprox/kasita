package cw.jazzproxy.kasita

import androidx.core.content.FileProvider

/**
 * In-app updates: shares the downloaded APK with the package installer. Its own subclass so the
 * manifest merger never mixes it up with a plugin that declares the plain androidx FileProvider.
 */
class UpdateFileProvider : FileProvider()
