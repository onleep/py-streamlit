# Мониторинг и анализ температур
## Технологии
### 1. Асинхронность
Функционал парсинга температуры полностью асинхронен, это позволяет выполнять несколько запросов одновременно.
```py
async def fetch_temp(city, apikey):
    URL = 'https://api.openweathermap.org/data/2.5/weather'
    params = {'q': city, 'appid': apikey, 'units': 'metric'}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(URL, params=params, timeout=10)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            st.error(e.response.text)
            return
        except Exception as e:
            st.error(e)
            return
        data = response.json()
        return data['main']['temp']
```
### 2. Распараллеленость
Имея возможность асинхронного парсинга температуры, стоит задача одновременно анализа всех городов. Для выполнения этой задачи основной функционал анализа вынесен в отдельную функцию **handle_city**, которая также является асинхронной. После чего ставится задача **asyncio.gather**, которая запускается обработку всех городов одновременно.
```py
tasks = [handle_city(city, data, apikey, placeholders[city], test=test) for city in cities]
await asyncio.gather(*tasks)
```
Также внутри **handle_city** был распараллелен анализ темперутуры благодаря **asyncio.to_thread**. Подход запуска функции в отдельном потоке используется, потому что внутри функции **analyze_temp** синхронный код из-за библиотеки **pandas**.
```py
city_data = await asyncio.to_thread(analyze_temp, data[data['city'] == city].copy())
```
### 3. Placeholders
Имея Асинхронность и Распараллеленость возникает проблема визуализации, один город может отрисоваться раньше другого, а также в блоке самого города информация может путаться местами. Для исправления этой ошибки созданы плейсхолдеры, которые по факту создают и обозначают пустое место, куда можно определенному городу записать данные.
```py
placeholders = {city: st.empty() for city in cities}
```
```py
opis_placeholder = st.empty()
anomalies_placeholder = st.empty()
chart_placeholder = st.empty()
trend_placeholder = st.empty()
if temp: temp_placeholder = st.empty()
```
### 4. Бенчмаркинг
Реализована система бенчмаркинга, которая проводится при каждом запуске анализа и выводится в streamlit. Бенчмаркингом является полное выполнение анализа городов, за исключением отрисовки графиков и стримлита. Существует 3 теста:
- 1: Распараллеленая обработка городов и анализа
- 2: Распараллеленая обработка городов
- 3: Последовательная обработка городов

При анализе одного города все 3 теста показывают схожие результаты. Но при анализе множества, 1 тест в среднем быстрее в х2 (с парсингом) по сравнение с 3 тестом, и немного быстрее чем второй. Это происходит благодаря тому, что в 1 и 2 варианте города обрабатываются одновремено и не дожидаются выполнения других.

## Анализ временных рядов
### 1. Создано меню управления настройками.
В сайдбар меню есть возможность загрузить данные, указать API Key и выбрать нужные города для анализа.
### 2. Расчет базовой статистики
Средняя, минимальная и максимальная температура по городу
### 2. Анализ температуры
Для города вычисляется скользящее среднее + стандартное отклонение и определяются аномалий на основе отклонений температуры от скользящего среднего.
```py
data['rolling_mean'] = data['temperature'].rolling(window=30).mean()
data['rolling_std'] = data['temperature'].rolling(window=30).std()
lower_bound = data['temperature'] < (data['rolling_mean'] - 2 * data['rolling_std'])
upper_bound = data['temperature'] > (data['rolling_mean'] + 2 * data['rolling_std'])
data['anomaly'] = lower_bound | upper_bound
```
### 3. Сезонная статистика
Определяются сезонные прпофили для города, высчитываются среднее и стандартное отклонение по температуре на сезон года.
```py
seasonal_stats = city_data.groupby('season')['temperature'].agg(['mean', 'std'])
```
### 4. Тренд температуры
Для города определяется положительный/отрицательный тренд температуры с помощью линейной регресии. В результате возвращается число, означающее среднее изменение в день.
```py
time = city_data['timestamp']
city_data['days'] = (time - time.min()).apply(lambda x: x.n)
X = [[day] for day in city_data['days'].tolist()]
y = city_data['temperature'].tolist()
model = LinearRegression().fit(X, y)
trend = model.coef_[0]
```
### 5. Парсинг температуры
Если указан API Key OpenWeatherMap, то для каждого выбраного города через асинхронную функцию будет спаршена актуальная температура.
```py
URL = 'https://api.openweathermap.org/data/2.5/weather'
params = {'q': city, 'appid': apikey, 'units': 'metric'}
async with httpx.AsyncClient() as client:
    try:
        response = await client.get(URL, params=params, timeout=10)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        st.error(e.response.text)
        return
    except Exception as e:
        st.error(e)
        return
    data = response.json()
    return data['main']['temp']
```
### 6. Анализ актуальной температуры
Если запрос на парсинг температуры оказался успешным, то производится анализ температуры текущего сезоне на основе сравнения от средней +- 2 * ст.отклонение за исторические данные. Если температура выходит за эти рамки - она считается аномальной.
```py
season_data = city_data[city_data['season'] == season]
mean_temp = season_data['temperature'].mean()
std_temp = season_data['temperature'].std()
lower_bound = mean_temp - 2 * std_temp
upper_bound = mean_temp + 2 * std_temp
return lower_bound <= temp <= upper_bound
```
## Интерактивная визуализация
### 1. Базовая статистика
- Средняя, минимальная и максимальная температура по городу
### 2. Аномалии
- Найденные аномалии температур по городу в виде таблицы
### 3. Временной ряд температур с аномалиями
- График с изображенной скользяжей средней температурой, общей температуры и выделенными красными точками аномалиями.
### 4. Сезонный профиль температур
- На графике для каждого сезона показана средняя температура и +- 1 стандартное отклонение.
### 5. Распределение температуры
- Гистограмма, которая позволяет оценить как в течение всего времени распределяется температура у города.
### 6. Температурный тренд города
- Отображение информации о том, положителен ли тренд и насколько в среднем изменяется температура.
### 7. Текущая температура
- Отображение текущей температуры с анализом, аномальна она или нет.
