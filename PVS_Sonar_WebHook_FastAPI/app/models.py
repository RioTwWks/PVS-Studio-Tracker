from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base


# Группа проектов
class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    internal_name = Column(String, unique=True, index=True, nullable=False)
    uuid = Column(String, unique=True, index=True, nullable=False)
    pm_email = Column(String, nullable=True)

    projects = relationship("Project", back_populates="group_rel")


# Язык программирования
class ProgrammingLanguage(Base):
    __tablename__ = "programming_languages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    preset_uuid = Column(String, nullable=True)

    projects = relationship("Project", back_populates="language_rel")


# Проект статического анализа кода
class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)

    # Внешние ключи
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    language_id = Column(Integer, ForeignKey("programming_languages.id"), nullable=True, index=True, default=1)

    # Обязательные поля (nullable=False)
    author_email = Column(String, nullable=False)
    sonar_project_name = Column(String, nullable=False, index=True)
    sonar_project_key = Column(String, nullable=False, index=True)
    cvs_system = Column(String, nullable=False)
    tfs_path = Column(String, nullable=False, index=True)
    another_branch = Column(String, nullable=False, default="", index=True)
    pvs_check_conf_name = Column(String, nullable=False)
    pvs_check_arch = Column(String, nullable=False)

    # Необязательные поля (могут быть пустыми)
    jira_project = Column(String, default="")
    sub_modules = Column(Boolean, default=False)
    life_time = Column(String)
    cmake_msbuild = Column(String)
    select_vcxproj = Column(String, default="")
    pvs_exclude_vcxproj = Column(String, default="")
    pvs_exclude_path = Column(String, default="")
    cmake_win_commands = Column(String, default="")
    cmake_linux_commands = Column(String, default="")
    disabled = Column(Boolean, default=False)
    last_processed_changeset = Column(String, default="")
    version = Column(String, default="")
    disable_jira = Column(Boolean, default=True)

    # Связи
    group_rel = relationship("Group", back_populates="projects")
    language_rel = relationship("ProgrammingLanguage", back_populates="projects")
    files = relationship("File", back_populates="project", cascade="all, delete-orphan")

    # Свойство для обратной совместимости (позволяет читать project.group как раньше)
    @property
    def group(self):
        return self.group_rel.internal_name if self.group_rel else None


# Файл проекта
class File(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)

    # Уникальность имени файла в рамках проекта
    __table_args__ = (UniqueConstraint("project_id", "filename", name="uq_project_filename"),)

    # Связи
    project = relationship("Project", back_populates="files")
    versions = relationship("Version", back_populates="file", cascade="all, delete-orphan")


# Версия файла
class Version(Base):
    __tablename__ = "versions"

    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    creation_date = Column(String, nullable=True)
    hash = Column(String, nullable=False, index=True)
    version = Column(String, nullable=False)

    # Уникальность хеша в рамках файла
    __table_args__ = (UniqueConstraint("file_id", "hash", name="uq_file_hash"),)

    # Связь с файлом
    file = relationship("File", back_populates="versions")
