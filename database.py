from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL
import datetime

Base = declarative_base()
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True)
    username = Column(String)
    level = Column(Integer, default=1)
    exp = Column(Integer, default=0)
    gold = Column(Integer, default=100)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Monster(Base):
    __tablename__ = 'monsters'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    rarity = Column(String)
    hp = Column(Integer)
    attack = Column(Integer)

class Inventory(Base):
    __tablename__ = 'inventory'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    item_name = Column(String)
    rarity = Column(String)
    quantity = Column(Integer, default=1)

Base.metadata.create_all(engine)