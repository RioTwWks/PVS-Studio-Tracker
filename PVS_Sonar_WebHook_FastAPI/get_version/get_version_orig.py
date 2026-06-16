from glob import glob
from os import getenv
from re import search

sonar_project_key = getenv('SONAR_PROJECT_KEY')
sonar_project_name = getenv('SONAR_PROJECT_NAME')
proj_dir = getenv('DIR_FOR_PYTHON')

major = None
minor = None
patch = None

if getenv('CMAKE_MSBUILD') == 'MSBuild':
	files = glob(proj_dir + '\\**\\*ersion-utf-8.rc*', recursive=True)
	for file in files:
		file_path = file
		print('DEBUG: Find file Version.rc with version: ' + file_path)
		with open(file_path, 'r+', encoding='cp866') as file:
			for line in file:
				match = search(r'.*FILEVERSION (\d+),(\d+),(\d+),\d+', line)
				if match:
					major = int(match.group(1))
					minor = int(match.group(2))
					patch = int(match.group(3))
	if not major and not minor and not patch:
		files = glob(proj_dir + '\\**\\*-utf-8.rc*', recursive=True)
		for file in files:
			file_path = file
			print('DEBUG: Find file .rc with version: ' + file_path)
			with open(file_path, 'r+', encoding='cp866') as file:
				for line in file:
					match = search(r'.*FILEVERSION (\d+),(\d+),(\d+),\d+', line)
					if match:
						major = int(match.group(1))
						minor = int(match.group(2))
						patch = int(match.group(3))
elif getenv('CMAKE_MSBUILD') == 'CMake':
	files = glob(proj_dir + '\\**\\*ersion.cmake*', recursive=True)
	for file in files:
		file_path = file
		print('DEBUG: Find file Version.cmake with version: ' + file_path)
		with open(file_path, 'r+') as file:
			for line in file:
				ver = search(r'.*VER.* \d+', line)
				if ver:
					if search(r'.*MAJ.*', line):
						major = search(r'(\d+)', line)
						major = int(major.group(1))
					elif search(r'.*MIN.*', line):
						minor = search(r'(\d+)', line)
						minor = int(minor.group(1))
					elif search(r'.*PATCH.*', line):
						patch = search(r'(\d+)', line)
						patch = int(patch.group(1))
						break
	if not major and not minor and not patch:
		file_name = search(r'.*[.](.*)', sonar_project_key)
		print ('DEBUG: File Version.cmake without version. Find: ' + file_name.group(1) + '.cmake')
		files = glob(proj_dir + '\\**\\' + file_name.group(1) + '.cmake*', recursive=True)
		for file in files:
			file_path = file
			print('DEBUG: Find file project_name.cmake with version: ' + file_path)
			with open(file_path, 'r+') as file:
				for line in file:
					ver = search(r'.*VER.* \d+', line)
					if ver:
						if search(r'.*MAJ.*', line):
							major = search(r'(\d+)', line)
							major = int(major.group(1))
						elif search(r'.*MIN.*', line):
							minor = search(r'(\d+)', line)
							minor = int(minor.group(1))
						elif search(r'.*PATCH.*', line):
							patch = search(r'(\d+)', line)
							patch = int(patch.group(1))
							break
else:
    raise ValueError('ERROR: CMAKE_MSBUILD is defined incorrectly')

print (f'DEBUG: Project Version {major}.{minor}.{patch}')

if major == None and minor == None and patch == None:
	raise ValueError('ERROR: Version not found')

params = """
sonar.sourceEncoding=CP1251
sonar.language=c++

sonar.sources=./

sonar.exclusions=build_dir/**,build_cmake/**,build.cmake/**,out/**,.git/**,**/*.cmake,**/*.doc,**/*.docx,**/*.ipch,**/*.rc,**/*.ico,**/*.cur,**/*.ini,**/*.gitignore,**/*.gitmodules,**/*.pas,**/*.props,**/*.txt,**/*.json,**/*.dpr,**/*.dproj,**/*.clang-format,**/*.sh,**/*.vcxproj,**/*.lim,**/*.data,**/*.sql,**/*.sln,**/*.filters,**/*.in,**/*.def,**/*.bat,**/*.bpg,**/*.dof,**/*.vssscc,**/*.lib,**/*.png,**/README,**/*.mc,**/COPYING,**/Makefile,**/version,**/*.cmd,**/*.p7s,**/*.dll,**/*.pc,**/FAQ,**/*.nupkg,**/*.py,**/*.profile,**/*.gz,**/PARDP,**/TRGEN,**/*.a,**/*.exe,**/*.vspscc,**/*.xml,**/*.inl,**/*.gitattributes,**/*.targets,**/*.doxy,**/*.log,**/*.bmp,**/*.wav,**/*.pdb,**/*.jpg,**/*.LIB,**/*.rule,**/*.bin,**/*.obj,**/*.recipe,**/*.tlog,**/*.lastbuildstate,**/*.stamp,**/*.depend,**/*.tmpl,**/*.ac,**/*.html,**/*.pl,**/*.am,**/*.supp,**/*.template,**/*.pump,**/*.ICO,**/*.BMP,**/*.RC,**/*.DEF,**/*.TXT,**/*.manifest,**/*.lua,**/*.css,**/*.gif,**/*.pdf,**/*.mdb,**/*.aps,**/*.user,**/*.list,**/*.cfg,**/*.Linux,**/*.Windows,**/*.md,**/*.h_bmp,**/*.htm,**/*.dsp,**/*.dsw,**/*.rc2,**/*.plg
sonar.pvs-studio.reportPath=pvs.plog
sonar.cxx.includeDirectories=c:/VC/include,c:/VC/sdk/Include
sonar.scm.enabled=false

sonar.scm.provider=git
"""

with open(proj_dir + '\\sonar-project.properties', 'w', encoding='cp1251') as f:
	f.write('sonar.projectKey=' + sonar_project_key + '\n' +
		'sonar.projectName=' + sonar_project_name + '\n\n' +
		f'sonar.projectVersion={major}.{minor}.{patch}\n' +
		params)
