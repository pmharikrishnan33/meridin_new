from app.database.mongodb import mongodb
from app.database.collections import collections

mongodb.connect()

print(collections.products)

mongodb.disconnect()