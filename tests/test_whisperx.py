"""WhisperX/local mode isolation, selected assets, alignment and independent caches."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave
import zipfile

import scribe as app


class WhisperXTests(unittest.TestCase):
    def test_tokenizer_setup_checks_archive_members_and_offline_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'punkt.zip'
            content = b'tokenizer fixture'
            with zipfile.ZipFile(archive, 'w') as out:
                out.writestr('punkt_tab/english/data', content)
            member = {'path': 'tokenizers/punkt_tab/english/data',
                      'archive_member': 'punkt_tab/english/data', 'size': len(content),
                      'sha256': hashlib.sha256(content).hexdigest()}
            manifest = {'files': [{'path': 'punkt.zip', 'sha256': app.digest_file(archive)}],
                        'whisperx': {'nltk': {'archive': 'punkt.zip', 'directory': 'nltk', 'members': [member]}}}
            with self.assertRaisesRegex(app.AppError, 'missing or damaged'):
                app.ensure_whisperx_tokenizers(root, manifest, True)
            app.ensure_whisperx_tokenizers(root, manifest, False)
            target = root / 'nltk' / member['path']
            self.assertEqual(target.read_bytes(), content)
            app.ensure_whisperx_tokenizers(root, manifest, True)
            target.write_bytes(b'damaged')
            with self.assertRaisesRegex(app.AppError, 'missing or damaged'):
                app.ensure_whisperx_tokenizers(root, manifest, True)
            app.ensure_whisperx_tokenizers(root, manifest, False)
            self.assertEqual(target.read_bytes(), content)
            member['path'] = '../outside'
            with self.assertRaisesRegex(app.AppError, 'Invalid tokenizer path'):
                app.ensure_whisperx_tokenizers(root, manifest, False)
            member['path'] = 'bad-hash'
            member['sha256'] = '0' * 64
            with self.assertRaisesRegex(app.AppError, 'SHA-256'):
                app.ensure_whisperx_tokenizers(root, manifest, False)
            self.assertFalse((root / 'nltk/bad-hash').exists())

    def test_five_modes_defaults_and_offline_priority(self):
        parser = app.build_parser()
        default = parser.parse_args([])
        self.assertEqual((default.transcription_model, default.diarization_model), ("whisperx", "nemotron"))
        for mode in [app.ONLINE_MODE, "whisperx", "mlx", app.COMBINED_MODE, app.ALL_MODE]:
            args = parser.parse_args(["--transcription-model", mode, "--offline", "--diarization-model", "community-1"])
            app.configure_mode(args)
            self.assertEqual(args.transcription_model, "mlx" if mode == "mlx" else "whisperx")
            self.assertEqual(args.diarization_model, "community-1")
            self.assertIsNone(args.summarize_model)
        for mode in ["whisper-local", "gpt-transcribe", "unknown"]:
            with self.subTest(mode=mode), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(["--transcription-model", mode])

    def test_old_mlx_final_log_resumes_only_under_explicit_mlx(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'meeting.mkv'
            source.write_bytes(b'recording')
            args = app.build_parser().parse_args(['--offline', '--transcription-model', 'mlx',
                '--output-dir', str(root / 'out')])
            args.cache_dir = root / 'cache'
            app.configure_mode(args)
            log, _ = app.output_paths(source, args.output_dir)
            app.atomic_write(log, 'Preserved MLX transcript')
            before = log.read_bytes(), log.stat().st_mtime_ns
            settings = app.recognition_settings(source, args)
            settings.pop('recognizer')
            cache = args.cache_dir / hashlib.sha256(str(source).encode()).hexdigest()[:16]
            app.save_json(app.output_state_path(cache, log), {'settings': settings,
                'selection': {'transcription_model': 'whisper-local'}, 'pipeline_complete': True})
            with patch.object(app, 'extract_audio') as extract:
                app.process_file(source, args, '')
                extract.assert_not_called()
                args.transcription_model = 'whisperx'
                with self.assertRaisesRegex(app.AppError, 'settings changed'):
                    app.process_file(source, args, '')
                extract.assert_not_called()
            self.assertEqual((log.read_bytes(), log.stat().st_mtime_ns), before)

    def test_community_is_local_and_does_not_receive_count_hints(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio=Path(tmp)/'audio.wav'
            with wave.open(str(audio),'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\0'*64000)
            frame=SimpleNamespace(itertuples=lambda:iter([
                SimpleNamespace(start=2.,end=3.,speaker='SPEAKER_00'),
                SimpleNamespace(start=.5,end=2.5,speaker='SPEAKER_01')]))
            pipeline=Mock(return_value=frame);load=Mock(return_value=pipeline)
            modules={'torch':SimpleNamespace(set_num_threads=Mock()),'whisperx':SimpleNamespace(),
                     'whisperx.diarize':SimpleNamespace(DiarizationPipeline=load)}
            with patch.dict(sys.modules,modules):
                voices=app.diarize(audio,Path('/models'),'community-1')
            self.assertEqual(voices,[{'start':.5,'end':2.5,'speaker':1},{'start':2.,'end':3.,'speaker':2}])
            self.assertEqual(pipeline.call_args.kwargs,{})
            self.assertEqual(len(pipeline.call_args.args[0]),64000)
            self.assertEqual(load.call_args.kwargs['model_name'],'/models/diarization/community-1')

    def test_setup_downloads_only_selected_assets_and_api_needs_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); resources=root/'resources'; models=root/'models'
            files=[]
            for group in ['whisperx','mlx','nemotron','community-1']:
                data=group.encode()
                files.append({'path':group+'/fixture','group':group,'size':len(data),
                    'sha256':hashlib.sha256(data).hexdigest(),'url':'https://example.test/'+group})
            app.save_json(resources/'models-manifest.json',{'files':files})
            seen=[]
            def download(request,**kwargs):
                seen.append(request)
                return io.BytesIO(request.full_url.rsplit('/',1)[-1].encode())
            with patch.object(app,'RESOURCE_DIR',resources), patch.object(app.urllib.request,'urlopen',download), \
                    patch.dict(os.environ,{'HF_TOKEN':'private-fixture'}):
                app.ensure_models(models)
                self.assertEqual({r.full_url for r in seen},{'https://example.test/whisperx','https://example.test/nemotron'})
                self.assertTrue(all(r.get_header('Authorization') is None for r in seen))
                seen.clear()
                app.ensure_models(models,transcription_model='mlx')
                self.assertEqual([r.full_url for r in seen],['https://example.test/mlx'])
                seen.clear()
                app.ensure_models(models,transcription_model=app.ONLINE_MODE,diarization_model='community-1')
                self.assertEqual(seen,[])
                app.ensure_models(models,offline=True)

    def test_gated_token_is_scoped_to_initial_hf_download_and_existing_assets_need_no_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); resources=root/'resources'; models=root/'models'; data=b'model'
            item={'path':'community/weights','group':'community-1','hf_auth':True,'size':len(data),
                  'sha256':hashlib.sha256(data).hexdigest(),'url':'https://huggingface.co/example/resolve/revision/model'}
            app.save_json(resources/'models-manifest.json',{'files':[item]})
            with patch.object(app,'RESOURCE_DIR',resources), patch.dict(os.environ,{},clear=True):
                with self.assertRaisesRegex(app.AppError,'HF_TOKEN'):
                    app.ensure_models(models,diarization_model='community-1')
            opener=Mock();opener.open.return_value=io.BytesIO(data)
            with patch.object(app,'RESOURCE_DIR',resources), patch.dict(os.environ,{'HF_TOKEN':'private-fixture'}), \
                    patch.object(app.urllib.request,'build_opener',return_value=opener):
                app.ensure_models(models,diarization_model='community-1')
                req=opener.open.call_args.args[0]
                self.assertEqual(req.get_header('Authorization'),'Bearer private-fixture')
                redirected=app.ModelRedirectHandler().redirect_request(req,None,302,'Found',{},'https://cdn.example/model')
                self.assertIsNone(redirected.get_header('Authorization'))
            with patch.object(app,'RESOURCE_DIR',resources), patch.dict(os.environ,{},clear=True), \
                    patch.object(app.urllib.request,'urlopen',side_effect=AssertionError('Network forbidden')):
                app.ensure_models(models,offline=True,diarization_model='community-1')

    def fake_whisperx(self, language='en', aligned=None, raw=None):
        raw=raw if raw is not None else {'language':language,'segments':[{'start':0.,'end':2.,'text':'Hello there','avg_logprob':-.1}]}
        aligned=aligned if aligned is not None else {'segments':[{'start':0.,'end':2.,'words':[
            {'word':'Hello','start':.1,'end':.5,'score':.001},{'word':'there','start':.6,'end':1.2,'score':.99}]}]}
        loader=Mock(return_value=SimpleNamespace(transcribe=Mock(return_value=raw)))
        align_loader=Mock(return_value=(object(),{}));align=Mock(return_value=aligned)
        nltk=SimpleNamespace(data=SimpleNamespace(path=[],find=Mock(return_value=True)),download=Mock(side_effect=AssertionError('No NLTK downloads')))
        modules={'torch':SimpleNamespace(set_num_threads=Mock()),'nltk':nltk,'whisperx':SimpleNamespace(),
                 'whisperx.asr':SimpleNamespace(load_model=loader),
                 'whisperx.alignment':SimpleNamespace(load_align_model=align_loader,align=align)}
        return modules,loader,align_loader,align

    def test_whisperx_uses_local_turbo_and_language_alignment_without_confusing_scores(self):
        import numpy as np
        aligned={'segments':[{'start':np.float64(0),'end':np.float64(2),'words':[
            {'word':'Hello','start':np.float64(.1),'end':np.float64(.5),'score':np.float32(.001)},
            {'word':'there','start':np.float64(.6),'end':np.float64(1.2),'score':np.float32(.99)}]}]}
        modules,loader,alignment,_=self.fake_whisperx(aligned=aligned)
        models=Path('/models')
        with patch.dict(sys.modules,modules):
            words=app.recognize([0.]*32000,models,'auto','Alice, Bob')
        self.assertEqual([w['text'] for w in words],[' Hello',' there'])
        self.assertFalse(any(w['unclear'] for w in words)) # Low alignment score is not low ASR confidence.
        json.dumps(words) # Native numpy scalars must not break checkpoint writes.
        self.assertTrue(loader.call_args.kwargs['local_files_only'])
        self.assertIsNone(loader.call_args.kwargs['language'])
        self.assertEqual(loader.call_args.kwargs['asr_options']['initial_prompt'],'Alice, Bob')
        self.assertTrue(alignment.call_args.kwargs['model_cache_only'])
        self.assertIn('whisperx/align/en',alignment.call_args.kwargs['model_name'])

    def test_untimed_words_are_retained_with_voice_uncertainty(self):
        aligned={'segments':[{'start':0.,'end':1.,'words':[{'word':'Alice'}]}]}
        modules,*_=self.fake_whisperx(aligned=aligned)
        with patch.dict(sys.modules,modules):
            words=app.recognize([0.]*32000,Path('/models'),'en','')
        self.assertTrue(words[0]['timing_uncertain'])
        turns=app.assign_speakers(words,[{'start':0.,'end':2.,'speaker':1}])
        self.assertIn('[speaker uncertain: Alice]',turns[0]['text'])
        aligned={'segments':[{'start':0.,'end':2.,'words':[
            {'word':'Hello','start':.1,'end':.5}, {'word':'Alice'},
            {'word':'there','start':1.,'end':1.5}]}]}
        modules,*_=self.fake_whisperx(aligned=aligned)
        with patch.dict(sys.modules,modules):
            words=app.recognize([0.]*32000,Path('/models'),'en','')
        turns=app.assign_speakers(words,[{'start':0.,'end':2.,'speaker':1}])
        self.assertEqual(turns[0]['text'],'Hello [speaker uncertain: Alice] there')

    def test_whisperx_rejects_unsupported_language_or_invalid_times_and_handles_silence(self):
        modules,_,alignment,_=self.fake_whisperx(language='de')
        with patch.dict(sys.modules,modules), self.assertRaisesRegex(app.AppError,'English and Russian'):
            app.recognize([0.]*32000,Path('/models'),'auto','')
        alignment.assert_not_called()
        modules,_,alignment,_=self.fake_whisperx(raw={'language':'en','segments':[]})
        with patch.dict(sys.modules,modules):
            self.assertEqual(app.recognize([0.]*32000,Path('/models'),'auto',''),[])
        alignment.assert_not_called()
        modules,*_=self.fake_whisperx(aligned={'segments':[{'start':0.,'end':2.,'words':[{'word':'bad','start':-1,'end':1}]}]})
        with patch.dict(sys.modules,modules), self.assertRaisesRegex(app.AppError,'invalid word timing'):
            app.recognize([0.]*32000,Path('/models'),'en','')

    def test_model_switch_invalidates_words_but_diarizer_switch_preserves_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'recording.mkv';source.write_bytes(b'input');audio=root/'audio.wav'
            with wave.open(str(audio),'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\0'*32000)
            args=app.build_parser().parse_args(['--offline']);app.configure_mode(args)
            settings=app.recognition_settings(source,args);cache=root/'cache'
            legacy={k:v for k,v in settings.items() if k not in ('recognizer','diarization')};legacy['speakers']=2
            words=[{'start':0.,'end':1.,'text':'Hello','unclear':False}]
            voices=[{'start':0.,'end':2.,'speaker':1}]
            app.save_json(cache/'words-stage.json',{'settings':legacy,'words':words})
            app.save_json(cache/'voices-stage.json',{'settings':{k:settings[k] for k in ['source','models','diarization']},'intervals':voices})
            with patch.object(app,'diarize') as voice,patch.object(app,'recognize',return_value=words) as recognize:
                app.local_recognition(audio,cache,settings,args)
                voice.assert_not_called();self.assertEqual(recognize.call_args.args[-1],'whisperx')
            args.diarization_model='community-1';changed=app.recognition_settings(source,args)
            with patch.object(app,'diarize',return_value=voices) as voice,patch.object(app,'recognize') as recognize:
                app.local_recognition(audio,cache,changed,args)
                voice.assert_called_once_with(audio,args.models_dir,'community-1');recognize.assert_not_called()
            args.transcription_model='mlx';changed=app.recognition_settings(source,args)
            with patch.object(app,'diarize') as voice,patch.object(app,'recognize',return_value=words) as recognize:
                app.local_recognition(audio,cache,changed,args)
                voice.assert_not_called();self.assertEqual(recognize.call_args.args[-1],'mlx')


if __name__=='__main__':
    unittest.main()
