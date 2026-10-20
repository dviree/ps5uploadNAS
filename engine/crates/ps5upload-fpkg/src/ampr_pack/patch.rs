//! Patching an LZ4 packed game: replacement files (a backport, a fix) put into a game whose
//! files are in AMPR LZ4 asset packs. A replacement for a file that is loose on disk is simply
//! written over it. One for a file that is inside the packs would never be read (the game is
//! served the packed copy), so its record in the pack manifest is turned into a loose one and
//! the new file goes on disk; a new file gets a loose record. `ampr_emu.index` gets the new
//! sizes. The packs, their chunks and the CRC sidecar stay as they are, and so do the files the
//! packer keeps on disk ([`super::pack::keep_on_disk`], Ghost of Yotei's boot files among them).

use super::format::{canonical, manifest_bytes, path_hash, FileRecord, Manifest, FILE_PACKED};
use crate::ampr_index::{self, Entry};
use crate::{format_err, Result};

/// The pack manifest and `ampr_emu.index` of a game folder, at its root.
pub const MANIFEST: &str = "ampr_assets.index";
pub const EMU_INDEX: &str = "ampr_emu.index";

/// What a patch changes, by path inside the game.
#[derive(Debug, Default, Clone, PartialEq, Eq, serde::Serialize)]
pub struct Patched {
    /// Files that were loose: written over.
    pub replaced: Vec<String>,
    /// Files that were inside the packs: now loose, the new file on disk.
    pub unpacked: Vec<String>,
    /// Files the game did not have.
    pub added: Vec<String>,
    /// The new `ampr_assets.index` and `ampr_emu.index`.
    #[serde(skip)]
    pub manifest: Vec<u8>,
    #[serde(skip)]
    pub emu_index: Vec<u8>,
}

/// The lookup key both indexes sort and match by: `\` as `/`, ASCII lowered.
fn key(app0_path: &str) -> Vec<u8> {
    app0_path
        .bytes()
        .map(|b| match b {
            b'\\' => b'/',
            b'A'..=b'Z' => b + 0x20,
            _ => b,
        })
        .collect()
}

/// `files` (path inside the game, size) patched into the indexes `manifest` and `emu_index`;
/// every changed record gets `mtime`. Nothing is written: the caller writes the files, then
/// the two indexes.
pub fn patch(
    manifest: &[u8],
    emu_index: &[u8],
    files: &[(String, u64)],
    mtime: i64,
) -> Result<Patched> {
    let m = Manifest::parse(manifest)?;
    let entries = ampr_index::parse(emu_index)
        .ok_or_else(|| crate::Error::Format(format!("{EMU_INDEX} is not readable")))?;
    if entries.len() != m.files.len() {
        return format_err(format!(
            "{MANIFEST} lists {} files and {EMU_INDEX} {}: they do not belong together",
            m.files.len(),
            entries.len()
        ));
    }
    // One row per file: its index entry and manifest record, in file-id order.
    let mut rows: Vec<(Entry, FileRecord)> = Vec::with_capacity(entries.len() + files.len());
    for (i, e) in entries.into_iter().enumerate() {
        let path = m.path(i)?;
        if key(path) != key(&format!("/app0/{}", e.path)) {
            return format_err(format!(
                "{MANIFEST} and {EMU_INDEX} disagree on file id {}",
                i + 1
            ));
        }
        rows.push((e, m.files[i].clone()));
    }
    let mut strings = m.strings.clone();
    let mut out = Patched::default();
    for (rel, size) in files {
        let app0 = canonical(&format!("/app0/{}", rel.trim_start_matches('/')))?;
        let rel = app0["/app0/".len()..].to_string();
        let k = key(&app0);
        let loose_record = |r: &FileRecord| FileRecord {
            path_hash: r.path_hash,
            logical_size: *size,
            mtime,
            path_offset: r.path_offset,
            path_length: r.path_length,
            ..FileRecord::default()
        };
        match rows
            .iter_mut()
            .find(|(e, _)| key(&format!("/app0/{}", e.path)) == k)
        {
            Some((e, r)) => {
                if r.flags & FILE_PACKED != 0 {
                    out.unpacked.push(e.path.clone());
                } else {
                    out.replaced.push(e.path.clone());
                }
                *r = loose_record(r);
                e.size = *size;
                e.mtime = mtime;
            }
            None => {
                let offset = strings.len() as u32;
                strings.extend_from_slice(app0.as_bytes());
                strings.push(0);
                let r = FileRecord {
                    path_hash: path_hash(&app0),
                    path_offset: offset,
                    path_length: app0.len() as u32,
                    ..FileRecord::default()
                };
                rows.push((
                    Entry {
                        path: rel.clone(),
                        size: *size,
                        mtime,
                    },
                    loose_record(&r),
                ));
                out.added.push(rel);
            }
        }
    }
    // File ids are the sorted order of both indexes.
    rows.sort_by_key(|(e, _)| key(&format!("/app0/{}", e.path)));
    let entries: Vec<Entry> = rows.iter().map(|(e, _)| e.clone()).collect();
    let records: Vec<FileRecord> = rows.into_iter().map(|(_, r)| r).collect();
    out.emu_index = ampr_index::build_entries(&entries).map_err(crate::Error::Format)?;
    out.manifest = manifest_bytes(&m.build_id, &records, &m.chunks, &m.packs, &strings)?;
    // What ampr_emu would refuse is refused here, before anything is written.
    Manifest::parse(&out.manifest)?;
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::super::{build, default_profile, Control, Reader};
    use super::*;
    use crate::source::{FolderSource, SourceTree};

    /// A packed game patched with a new eboot (loose), a new version of a packed file and a
    /// file it did not have: the manifest and index agree, the replaced packed file is loose
    /// now, the other packed files still read from the packs.
    #[test]
    fn a_patch_goes_over_loose_files_and_unpacks_packed_ones() {
        let root = std::env::temp_dir().join(format!("ampr-patch-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        for (p, d) in [
            ("eboot.bin", vec![1u8; 100]),
            ("data/a.bin", vec![b'a'; 70_000]),
            ("psml_package/KPN9_v070.psp", vec![b'k'; 70_000]),
        ] {
            let f = root.join(p);
            std::fs::create_dir_all(f.parent().unwrap()).unwrap();
            std::fs::write(f, d).unwrap();
        }
        let mut tree = FolderSource::open(&root).unwrap();
        let listing: Vec<(String, u64)> = tree
            .files()
            .iter()
            .map(|f| (f.path.clone(), f.size))
            .collect();
        let index = ampr_index::build(&listing, 7).unwrap();
        let entries = ampr_index::parse(&index).unwrap();
        let config = default_profile(9, 16);
        let out = build(&entries, &mut tree, &config, &root, &mut Control::default()).unwrap();
        out.write_small_files(&root).unwrap();
        std::fs::write(root.join(EMU_INDEX), &index).unwrap();
        assert!(out.packed.iter().any(|p| p == "psml_package/KPN9_v070.psp"));

        let manifest = std::fs::read(root.join(MANIFEST)).unwrap();
        let p = patch(
            &manifest,
            &index,
            &[
                ("eboot.bin".into(), 200),
                ("psml_package/KPN9_v070.psp".into(), 5),
                ("fakelib/libScePsml.sprx".into(), 9),
            ],
            99,
        )
        .unwrap();
        assert_eq!(p.replaced, ["eboot.bin"]);
        assert_eq!(p.unpacked, ["psml_package/KPN9_v070.psp"]);
        assert_eq!(p.added, ["fakelib/libScePsml.sprx"]);

        let m = Manifest::parse(&p.manifest).unwrap();
        let e = ampr_index::parse(&p.emu_index).unwrap();
        assert_eq!(m.files.len(), 4);
        assert_eq!(e.len(), 4);
        for (i, entry) in e.iter().enumerate() {
            assert_eq!(m.path(i).unwrap(), format!("/app0/{}", entry.path));
        }
        let at = |path: &str| e.iter().position(|x| x.path == path).unwrap();
        let psp = &m.files[at("psml_package/KPN9_v070.psp")];
        assert!(!psp.packed());
        assert_eq!(
            (psp.logical_size, e[at("psml_package/KPN9_v070.psp")].size),
            (5, 5)
        );
        assert!(!m.files[at("fakelib/libScePsml.sprx")].packed());
        assert!(m.files[at("data/a.bin")].packed());

        // The untouched packed file still reads from the packs with the new manifest.
        std::fs::write(root.join(MANIFEST), &p.manifest).unwrap();
        let mut folder = FolderSource::open(&root).unwrap();
        let reader = Reader::open(&mut folder, MANIFEST).unwrap();
        let i = reader.find("data/a.bin").unwrap();
        assert_eq!(
            reader.read_file(i, &mut folder, "").unwrap(),
            vec![b'a'; 70_000]
        );
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn indexes_that_do_not_belong_together_are_refused() {
        let index = ampr_index::build(&[("a.bin".into(), 1)], 1).unwrap();
        assert!(patch(b"nonsense", &index, &[], 1).is_err());
    }
}
