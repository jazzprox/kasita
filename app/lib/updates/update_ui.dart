import 'dart:async';

import 'package:flutter/material.dart' hide Text;

import '../widgets.dart';
import 'update_logic.dart';
import 'updater.dart';
import '../i18n.dart';

/// Update: download (cancellable), make sure Kasita may install apps, open Android's installer.
Future<void> runUpdate(BuildContext context) async {
  if (updater.downloading || updater.latest == null) return;
  final String path;
  try {
    path = await updater.download();
  } on DownloadCancelled {
    if (context.mounted) toast(context, 'Download cancelled');
    return;
  } catch (e) {
    if (context.mounted) toast(context, "Couldn't download the update. Try again later.", error: true);
    return;
  }
  if (!context.mounted) return;
  try {
    if (!await updater.canInstall()) {
      if (!context.mounted) return;
      final explained = await updater.explainedInstall();
      if (!context.mounted) return;
      if (!explained) {
        final go = await showDialog<bool>(
          context: context,
          builder: (c) => AlertDialog(
            title: const Text('Allow updates'),
            content: const Text(
              'Android asks once whether Kasita may install apps. '
              'Switch on "Allow from this source", then come back here.',
            ),
            actions: [
              TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Not now')),
              FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Open settings')),
            ],
          ),
        );
        if (go != true || !context.mounted) return;
      } else {
        toast(context, 'Allow Kasita to install apps, then come back');
      }
      // back from the settings page = the app resumes
      final back = Completer<void>();
      final listener = AppLifecycleListener(onResume: () => back.isCompleted ? null : back.complete());
      try {
        if (!await updater.openInstallSettings()) throw Exception('no settings page');
        await back.future.timeout(const Duration(minutes: 10));
      } finally {
        listener.dispose();
      }
      if (!await updater.canInstall()) {
        if (context.mounted) toast(context, 'Kasita may not install apps yet. Tap Update again once allowed.');
        return;
      }
    }
    await updater.install(path);
  } catch (_) {
    if (context.mounted) toast(context, "Couldn't open the installer", error: true);
  }
}

void _showNotes(BuildContext context, ReleaseInfo rel) {
  final notes = shortNotes(rel.notes, max: 12);
  showDialog(
    context: context,
    builder: (c) => AlertDialog(
      title: Text("What's new in build ${rel.build}"),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (notes.isEmpty) const Text('No notes for this build.'),
            for (final n in notes) Padding(padding: const EdgeInsets.only(bottom: 6), child: Text('• $n')),
          ],
        ),
      ),
      actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('Close'))],
    ),
  );
}

String _percent(double p) => '${(p * 100).round()}%';

/// The home-screen card: "Update available: build N". Nothing on the web, when up to date or
/// for 24 hours after "Not now".
class UpdateBanner extends StatelessWidget {
  const UpdateBanner({super.key});

  @override
  Widget build(BuildContext context) {
    if (!updatesSupported) return const SizedBox.shrink();
    return ListenableBuilder(
      listenable: updater,
      builder: (context, _) {
        final rel = updater.latest;
        if (rel == null || !updater.offer) return const SizedBox.shrink();
        final cs = Theme.of(context).colorScheme;
        final progress = updater.progress;
        return Card(
          margin: const EdgeInsets.fromLTRB(12, 4, 12, 8),
          color: cs.secondaryContainer,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 8, 4),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.system_update_outlined, color: cs.onSecondaryContainer),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        progress == null
                            ? 'Update available: build ${rel.build}'
                            : 'Downloading… ${_percent(progress)}',
                        style: TextStyle(fontWeight: FontWeight.w600, color: cs.onSecondaryContainer),
                      ),
                    ),
                  ],
                ),
                if (progress != null)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(36, 8, 8, 0),
                    child: LinearProgressIndicator(value: progress),
                  ),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: progress != null
                      ? [TextButton(onPressed: updater.cancel, child: const Text('Cancel'))]
                      : [
                          TextButton(onPressed: () => _showNotes(context, rel), child: const Text("What's new")),
                          const Spacer(),
                          TextButton(onPressed: updater.snooze, child: const Text('Not now')),
                          const SizedBox(width: 4),
                          FilledButton(onPressed: () => runUpdate(context), child: const Text('Update')),
                        ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// More: "Check for updates" (own build vs the latest) and the "Automatically check" switch.
class UpdateSettingsTiles extends StatelessWidget {
  const UpdateSettingsTiles({super.key});

  Future<void> _check(BuildContext context) async {
    final ok = await updater.check();
    if (!context.mounted) return;
    if (!ok) {
      toast(context, "Couldn't reach GitHub. Try again later.", error: true);
    } else if (!updater.available) {
      toast(context, 'Kasita is up to date');
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!updatesSupported) return const SizedBox.shrink();
    return ListenableBuilder(
      listenable: updater,
      builder: (context, _) {
        final own = updater.current, rel = updater.latest, progress = updater.progress;
        final ownText = own == null ? 'This build' : 'Build $own';
        final String status;
        if (progress != null) {
          status = 'Downloading build ${rel?.build}… ${_percent(progress)}';
        } else if (updater.checking) {
          status = '$ownText · checking…';
        } else if (updater.available) {
          status = 'Build ${rel!.build} available · you have ${ownText.toLowerCase()}';
        } else if (updater.checkFailed) {
          status = "$ownText · couldn't check";
        } else if (rel != null) {
          status = '$ownText — up to date';
        } else {
          status = ownText;
        }
        return Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.system_update_outlined),
              title: const Text('Check for updates'),
              subtitle: Text(status),
              trailing: progress != null
                  ? TextButton(onPressed: updater.cancel, child: const Text('Cancel'))
                  : updater.available
                  ? FilledButton.tonal(onPressed: () => runUpdate(context), child: const Text('Update'))
                  : updater.checking
                  ? const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2))
                  : null,
              onTap: updater.checking || progress != null ? null : () => _check(context),
            ),
            SwitchListTile(
              secondary: const Icon(Icons.update),
              title: const Text('Automatically check'),
              subtitle: const Text('Looks for a new build every 6 hours'),
              value: updater.auto,
              onChanged: updater.setAuto,
            ),
          ],
        );
      },
    );
  }
}
