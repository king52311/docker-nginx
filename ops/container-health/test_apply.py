import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('health_apply',Path(__file__).with_name('apply.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class HealthMigrationTests(unittest.TestCase):
 def source(self):
  return {'Id':'old123','Name':'/app','Image':'sha256:exact','Config':{'Image':'floating:latest','Env':['PRIVATE=secret'],'Labels':{}},'State':{'Running':True},'HostConfig':{'Binds':['/data:/data:ro'],'RestartPolicy':{'Name':'always'},'NetworkMode':'custom','PortBindings':{'80/tcp':[{'HostPort':'8080'}]}},'Mounts':[{'Type':'bind','Destination':'/data','Source':'/data','RW':False},{'Type':'volume','Destination':'/state','Source':'/var/lib/docker/volumes/anon/_data','Name':'anon','RW':True}],'NetworkSettings':{'Networks':{'custom':{'Aliases':['app','old123'],'IPAMConfig':{'IPv4Address':'172.20.0.2'}}}}}
 def test_preserves_image_volume_ports_network_and_secrets_without_mutation(self):
  old=self.source();before=copy.deepcopy(old)
  body=m.create_body(old,{'Test':['CMD','true']},Path('/probe'),'revision')
  self.assertEqual(old,before)
  self.assertEqual(body['Image'],'sha256:exact')
  self.assertIn('anon:/state:rw',body['HostConfig']['Binds'])
  self.assertEqual(body['HostConfig']['PortBindings'],old['HostConfig']['PortBindings'])
  self.assertEqual(body['NetworkingConfig']['EndpointsConfig']['custom'],{'Aliases':['app'],'IPAMConfig':{'IPv4Address':'172.20.0.2'}})
  self.assertEqual(body['Env'],['PRIVATE=secret'])
 def test_failed_candidate_is_removed_and_old_policy_network_service_restored(self):
  old=self.source();calls=[]
  class Fake:
   def inspect(self,name):return old
   def call(self,method,path,body=None,allow=()):
    calls.append((method,path,body))
    return {'Id':'new123'} if path.startswith('/containers/create') else None
  with tempfile.TemporaryDirectory() as td,patch.object(m,'wait_healthy',side_effect=RuntimeError('bad')):
   with self.assertRaisesRegex(RuntimeError,'original container restored'):
    m.apply_one(Fake(),'app',{'Test':['CMD','false']},None,'rev',Path(td))
  self.assertTrue(any(method=='DELETE' and 'new123' in p for method,p,b in calls))
  self.assertTrue(any(p=='/networks/custom/connect' for _,p,_ in calls))
  self.assertTrue(any(p.endswith('/old123/update') and b=={'RestartPolicy':{'Name':'always'}} for _,p,b in calls))
  self.assertEqual(calls[-1][1],'/containers/old123/start')
 def test_stop_failure_never_renames_or_deletes_original(self):
  old=self.source();calls=[]
  class Fake:
   def inspect(self,name):return old
   def call(self,method,path,body=None,allow=()):
    calls.append(path)
    if '/stop?' in path:raise RuntimeError('failure')
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(RuntimeError):m.apply_one(Fake(),'app',{'Test':['CMD','false']},None,'rev',Path(td))
  self.assertFalse(any('/rename' in p or '/create' in p for p in calls))

if __name__=='__main__':unittest.main()
